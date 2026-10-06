// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title AgentVault — coffre on-chain dont les dépenses par un agent IA sont bornées par une politique.
/// @notice L'agent ne peut QUE demander des paiements. Il ne peut ni changer les règles, ni faire d'appel arbitraire.
///         Les violations de politique ne revert pas : elles émettent PaymentBlocked (piste d'audit on-chain).
///
/// Défenses (toutes vérifiées on-chain, donc valables même si l'agent ET le serveur sont compromis) :
///  - liste blanche de destinataires + délai d'activation (anti « changement de RIB »)
///  - plafond par transaction et par jour, validation humaine au-dessus d'un seuil (avec expiration)
///  - adresses appâts (canary) : un paiement vers l'une d'elles gèle le coffre
///  - disjoncteur : trop de paiements refusés dans la journée -> pause automatique
///  - clé d'agent à durée de vie limitée, rôle guardian (peut geler, jamais dégeler ni dépenser)
///  - transfert de propriété en deux étapes, ancrage on-chain des rapports d'audit
contract AgentVault {
    enum Status { Executed, Queued, Blocked }

    enum BlockReason {
        None,
        Paused,
        RecipientNotAllowed,
        TokenNotAllowed,
        OverTxLimit,
        OverDailyLimit,
        ZeroAmount,
        RecipientNotYetActive,
        TooManyPending,
        AgentExpired,
        CanaryTriggered
    }

    struct Limits {
        uint128 maxPerTx;          // 0 = token interdit
        uint128 dailyLimit;
        uint128 approvalThreshold; // montant >= seuil -> validation humaine (0 = jamais)
    }

    struct Pending {
        address token;
        address to;
        uint256 amount;
        string memo;
        uint64 createdAt;
        bool done;
    }

    address public constant NATIVE = address(0);
    uint256 public constant MAX_MEMO_BYTES = 140;
    uint256 public constant MAX_OPEN_PENDING = 10;
    uint256 public constant PENDING_TTL = 3 days;

    address public owner;
    address public pendingOwner;
    address public guardian;
    address public agent;
    uint64 public agentValidUntil;   // 0 = pas d'expiration
    bool public paused;

    uint64 public recipientDelay;    // délai avant qu'un nouveau destinataire soit payable
    uint32 public maxBlockedPerDay;  // disjoncteur (0 = désactivé)
    uint32 public blockedToday;
    uint64 public blockedDay;
    uint256 public openPending;

    mapping(address token => Limits) public limits;
    mapping(address recipient => bool) public allowedRecipient;
    mapping(address recipient => uint64) public activeFrom;
    mapping(address => bool) public isCanary;
    mapping(address token => uint256) public spentToday;
    mapping(address token => uint256) public spentDay;
    Pending[] public pending;

    uint256 private _lock = 1;

    event PaymentExecuted(address indexed token, address indexed to, uint256 amount, string memo);
    event PaymentQueued(uint256 indexed id, address indexed token, address indexed to, uint256 amount, string memo);
    event PaymentBlocked(BlockReason indexed reason, address indexed token, address indexed to, uint256 amount, string memo);
    event PaymentApproved(uint256 indexed id);
    event PaymentRejected(uint256 indexed id);
    event AgentChanged(address indexed agent, uint64 validUntil);
    event GuardianChanged(address indexed guardian);
    event LimitsChanged(address indexed token, uint128 maxPerTx, uint128 dailyLimit, uint128 approvalThreshold);
    event RecipientChanged(address indexed recipient, bool allowed, uint64 activeFrom);
    event RecipientDelayChanged(uint64 delay);
    event CanaryChanged(address indexed canary, bool enabled);
    event CircuitBreakerChanged(uint32 maxBlockedPerDay);
    event CircuitBreakerTripped(uint32 blockedToday);
    event CanaryAlert(address indexed canary, uint256 amount);
    event Paused(bool paused, address indexed by);
    event Withdrawn(address indexed token, address indexed to, uint256 amount);
    event OwnershipTransferStarted(address indexed from, address indexed to);
    event OwnershipTransferred(address indexed from, address indexed to);
    event ReportAnchored(bytes32 indexed hash, string uri);

    error NotOwner();
    error NotAgent();
    error NotGuardian();
    error ZeroAddress();
    error InvalidPending();
    error PendingExpired();
    error TransferFailed();
    error MemoTooLong();
    error NotAContract();
    error Reentrancy();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    modifier nonReentrant() {
        if (_lock != 1) revert Reentrancy();
        _lock = 2;
        _;
        _lock = 1;
    }

    constructor(address _agent) {
        if (_agent == address(0)) revert ZeroAddress();
        owner = msg.sender;
        agent = _agent;
        emit AgentChanged(_agent, 0);
        emit OwnershipTransferred(address(0), msg.sender);
    }

    receive() external payable {}

    // ------------------------------------------------------------------ Agent

    function requestPayment(address token, address to, uint256 amount, string calldata memo)
        external
        nonReentrant
        returns (Status status, uint256 pendingId)
    {
        if (msg.sender != agent) revert NotAgent();
        if (bytes(memo).length > MAX_MEMO_BYTES) revert MemoTooLong();

        BlockReason reason = _check(token, to, amount);
        if (reason != BlockReason.None) {
            emit PaymentBlocked(reason, token, to, amount, memo);
            if (reason == BlockReason.CanaryTriggered) {
                emit CanaryAlert(to, amount);
                _pause(address(this));
            } else if (reason != BlockReason.Paused) {
                _countBlocked();
            }
            return (Status.Blocked, 0);
        }

        Limits memory l = limits[token];
        if (l.approvalThreshold != 0 && amount >= l.approvalThreshold) {
            pending.push(Pending(token, to, amount, memo, uint64(block.timestamp), false));
            pendingId = pending.length - 1;
            openPending++;
            emit PaymentQueued(pendingId, token, to, amount, memo);
            return (Status.Queued, pendingId);
        }

        _addSpent(token, amount);
        _transfer(token, to, amount);
        emit PaymentExecuted(token, to, amount, memo);
        return (Status.Executed, 0);
    }

    function previewPayment(address token, address to, uint256 amount) external view returns (Status, BlockReason) {
        BlockReason reason = _check(token, to, amount);
        if (reason != BlockReason.None) return (Status.Blocked, reason);
        Limits memory l = limits[token];
        if (l.approvalThreshold != 0 && amount >= l.approvalThreshold) return (Status.Queued, BlockReason.None);
        return (Status.Executed, BlockReason.None);
    }

    // ------------------------------------------------------------------ Owner (humain)

    /// @notice Valide un paiement en attente. Les règles dures (pause, liste blanche, token, canary) sont revérifiées :
    ///         un destinataire retiré entre-temps ne peut plus être payé. Le montant compte dans la dépense du jour.
    function approve(uint256 id) external onlyOwner nonReentrant {
        Pending storage p = _open(id);
        if (block.timestamp > p.createdAt + PENDING_TTL) revert PendingExpired();
        if (paused || !allowedRecipient[p.to] || isCanary[p.to] || limits[p.token].maxPerTx == 0) {
            revert InvalidPending();
        }
        p.done = true;
        openPending--;
        _addSpent(p.token, p.amount);
        emit PaymentApproved(id);
        _transfer(p.token, p.to, p.amount);
        emit PaymentExecuted(p.token, p.to, p.amount, p.memo);
    }

    /// @notice Rejette un paiement en attente (aussi possible après expiration, pour libérer la place).
    function reject(uint256 id) external onlyOwner {
        _open(id).done = true;
        openPending--;
        emit PaymentRejected(id);
    }

    function setAgent(address _agent, uint64 validUntil) external onlyOwner {
        if (_agent == address(0)) revert ZeroAddress();
        agent = _agent;
        agentValidUntil = validUntil;
        emit AgentChanged(_agent, validUntil);
    }

    /// @dev address(0) est autorisé : il désactive le guardian.
    function setGuardian(address _guardian) external onlyOwner {
        guardian = _guardian;
        emit GuardianChanged(_guardian);
    }

    function setLimits(address token, uint128 maxPerTx, uint128 dailyLimit, uint128 approvalThreshold)
        external
        onlyOwner
    {
        if (token != NATIVE && token.code.length == 0) revert NotAContract();
        limits[token] = Limits(maxPerTx, dailyLimit, approvalThreshold);
        emit LimitsChanged(token, maxPerTx, dailyLimit, approvalThreshold);
    }

    /// @notice Ajoute/retire un destinataire. Un ajout n'est payable qu'après `recipientDelay`.
    function setRecipient(address recipient, bool allowed) external onlyOwner {
        if (recipient == address(0)) revert ZeroAddress();
        allowedRecipient[recipient] = allowed;
        uint64 from = allowed ? uint64(block.timestamp) + recipientDelay : 0;
        activeFrom[recipient] = from;
        emit RecipientChanged(recipient, allowed, from);
    }

    function setRecipientDelay(uint64 delay) external onlyOwner {
        recipientDelay = delay;
        emit RecipientDelayChanged(delay);
    }

    function setCanary(address canary, bool enabled) external onlyOwner {
        isCanary[canary] = enabled;
        emit CanaryChanged(canary, enabled);
    }

    function setCircuitBreaker(uint32 _maxBlockedPerDay) external onlyOwner {
        maxBlockedPerDay = _maxBlockedPerDay;
        emit CircuitBreakerChanged(_maxBlockedPerDay);
    }

    /// @notice Owner : pause ou reprise. Guardian : pause uniquement (il ne peut jamais relancer les paiements).
    function setPaused(bool _paused) external {
        if (msg.sender == owner) {
            paused = _paused;
            if (!_paused) blockedToday = 0;
            emit Paused(_paused, msg.sender);
        } else if (msg.sender == guardian && guardian != address(0) && _paused) {
            _pause(msg.sender);
        } else {
            revert NotGuardian();
        }
    }

    function withdraw(address token, address to, uint256 amount) external onlyOwner nonReentrant {
        if (to == address(0)) revert ZeroAddress();
        _transfer(token, to, amount);
        emit Withdrawn(token, to, amount);
    }

    /// @dev address(0) est autorisé : il annule un transfert en cours (le nouvel owner doit accepter).
    function transferOwnership(address to) external onlyOwner {
        pendingOwner = to;
        emit OwnershipTransferStarted(owner, to);
    }

    function acceptOwnership() external {
        if (msg.sender != pendingOwner) revert NotOwner();
        emit OwnershipTransferred(owner, msg.sender);
        owner = msg.sender;
        pendingOwner = address(0);
    }

    /// @notice Scelle l'empreinte (SHA-256) d'un rapport d'audit : preuve horodatée qu'il n'a pas été modifié.
    function anchorReport(bytes32 hash, string calldata uri) external {
        if (msg.sender != owner && msg.sender != guardian) revert NotGuardian();
        emit ReportAnchored(hash, uri);
    }

    function pendingCount() external view returns (uint256) {
        return pending.length;
    }

    // ------------------------------------------------------------------ Interne

    function _check(address token, address to, uint256 amount) internal view returns (BlockReason) {
        if (paused) return BlockReason.Paused;
        if (agentValidUntil != 0 && block.timestamp > agentValidUntil) return BlockReason.AgentExpired;
        if (isCanary[to]) return BlockReason.CanaryTriggered;
        if (amount == 0) return BlockReason.ZeroAmount;
        if (!allowedRecipient[to]) return BlockReason.RecipientNotAllowed;
        if (block.timestamp < activeFrom[to]) return BlockReason.RecipientNotYetActive;
        Limits memory l = limits[token];
        if (l.maxPerTx == 0) return BlockReason.TokenNotAllowed;
        if (amount > l.maxPerTx) return BlockReason.OverTxLimit;
        if (_spent(token) + amount > l.dailyLimit) return BlockReason.OverDailyLimit;
        if (l.approvalThreshold != 0 && amount >= l.approvalThreshold && openPending >= MAX_OPEN_PENDING) {
            return BlockReason.TooManyPending;
        }
        return BlockReason.None;
    }

    function _open(uint256 id) internal view returns (Pending storage p) {
        if (id >= pending.length) revert InvalidPending();
        p = pending[id];
        if (p.done) revert InvalidPending();
    }

    function _spent(address token) internal view returns (uint256) {
        // Égalité de numéros de JOUR (pas de timestamps) : voulue. Un validateur ne peut décaler l'horloge que de
        // quelques secondes, ce qui ne permet pas de contourner le plafond journalier.
        // slither-disable-next-line incorrect-equality,timestamp
        return spentDay[token] == block.timestamp / 1 days ? spentToday[token] : 0;
    }

    function _addSpent(address token, uint256 amount) internal {
        spentToday[token] = _spent(token) + amount;
        spentDay[token] = block.timestamp / 1 days;
    }

    function _countBlocked() internal {
        uint64 today = uint64(block.timestamp / 1 days);
        if (blockedDay != today) {
            blockedDay = today;
            blockedToday = 0;
        }
        blockedToday++;
        if (maxBlockedPerDay != 0 && blockedToday >= maxBlockedPerDay && !paused) {
            emit CircuitBreakerTripped(blockedToday);
            _pause(address(this));
        }
    }

    function _pause(address by) internal {
        paused = true;
        emit Paused(true, by);
    }

    function _transfer(address token, address to, uint256 amount) internal {
        bool ok;
        if (token == NATIVE) {
            (ok,) = to.call{value: amount}("");
        } else {
            if (token.code.length == 0) revert NotAContract();
            bytes memory data;
            (ok, data) = token.call(abi.encodeWithSignature("transfer(address,uint256)", to, amount));
            ok = ok && (data.length == 0 || abi.decode(data, (bool)));
        }
        if (!ok) revert TransferFailed();
    }
}
