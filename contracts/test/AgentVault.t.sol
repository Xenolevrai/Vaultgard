// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AgentVault} from "../src/AgentVault.sol";

contract MockToken {
    mapping(address => uint256) public balanceOf;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

/// Token qui renvoie false au lieu de revert (ERC20 non standard).
contract FalseToken {
    function transfer(address, uint256) external pure returns (bool) {
        return false;
    }
}

/// Destinataire malveillant : tente de rappeler le coffre pendant qu'il reçoit des AVAX (réentrance).
contract ReentrantRecipient {
    AgentVault public vault;
    bool public reentered;
    bool public reentrySucceeded;

    function setVault(AgentVault v) external {
        vault = v;
    }

    receive() external payable {
        if (reentered) return;
        reentered = true;
        try vault.requestPayment(address(0), address(this), 0.01 ether, "re") {
            reentrySucceeded = true;
        } catch {}
        try vault.approve(1) {
            reentrySucceeded = true;
        } catch {}
    }
}

contract AgentVaultTest is Test {
    AgentVault vault;
    MockToken usdc;
    address agent = makeAddr("agent");
    address supplier = makeAddr("supplier");
    address attacker = makeAddr("attacker");
    address guardian = makeAddr("guardian");
    address canary = makeAddr("canary");
    address constant NATIVE = address(0);

    function setUp() public {
        vm.warp(1_760_000_000);
        vault = new AgentVault(agent);
        usdc = new MockToken();
        vm.deal(address(vault), 100 ether);
        usdc.mint(address(vault), 1_000_000e6);
        vault.setRecipient(supplier, true);
        vault.setLimits(NATIVE, 5 ether, 10 ether, 3 ether);
        vault.setLimits(address(usdc), 500e6, 1_000e6, 0);
        vault.setGuardian(guardian);
        vault.setCanary(canary, true);
    }

    function _pay(address token, address to, uint256 amount) internal returns (AgentVault.Status s, uint256 id) {
        vm.prank(agent);
        return vault.requestPayment(token, to, amount, "test");
    }

    function _reason(address token, address to, uint256 amount) internal view returns (AgentVault.BlockReason r) {
        (, r) = vault.previewPayment(token, to, amount);
    }

    // ---------------------------------------------------------------- cas nominaux

    function test_PaysAllowedRecipientUnderLimits() public {
        (AgentVault.Status s,) = _pay(NATIVE, supplier, 1 ether);
        assertEq(uint256(s), uint256(AgentVault.Status.Executed));
        assertEq(supplier.balance, 1 ether);
    }

    function test_Erc20Payment() public {
        _pay(address(usdc), supplier, 100e6);
        assertEq(usdc.balanceOf(supplier), 100e6);
    }

    function test_PreviewMatchesExecution() public {
        (AgentVault.Status s, AgentVault.BlockReason r) = vault.previewPayment(NATIVE, attacker, 1 ether);
        assertEq(uint256(s), uint256(AgentVault.Status.Blocked));
        assertEq(uint256(r), uint256(AgentVault.BlockReason.RecipientNotAllowed));
        (AgentVault.Status s2,) = _pay(NATIVE, attacker, 1 ether);
        assertEq(uint256(s2), uint256(AgentVault.Status.Blocked));
    }

    // ---------------------------------------------------------------- politique

    function test_BlocksUnknownRecipient_NoRevert_EmitsEvent() public {
        vm.expectEmit(true, true, true, true);
        emit AgentVault.PaymentBlocked(AgentVault.BlockReason.RecipientNotAllowed, NATIVE, attacker, 1 ether, "test");
        (AgentVault.Status s,) = _pay(NATIVE, attacker, 1 ether);
        assertEq(uint256(s), uint256(AgentVault.Status.Blocked));
        assertEq(attacker.balance, 0);
    }

    function test_BlocksOverTxLimit() public {
        assertEq(uint256(_reason(NATIVE, supplier, 6 ether)), uint256(AgentVault.BlockReason.OverTxLimit));
    }

    function test_BlocksZeroAmount() public {
        assertEq(uint256(_reason(NATIVE, supplier, 0)), uint256(AgentVault.BlockReason.ZeroAmount));
    }

    function test_BlocksTokenNotAllowed() public {
        assertEq(uint256(_reason(address(0xBEEF), supplier, 1)), uint256(AgentVault.BlockReason.TokenNotAllowed));
    }

    function test_DailyLimitAndReset() public {
        for (uint256 i; i < 3; i++) _pay(NATIVE, supplier, 2.5 ether);
        assertEq(uint256(_reason(NATIVE, supplier, 2.6 ether)), uint256(AgentVault.BlockReason.OverDailyLimit));
        vm.warp(block.timestamp + 1 days);
        (AgentVault.Status s,) = _pay(NATIVE, supplier, 2.6 ether);
        assertEq(uint256(s), uint256(AgentVault.Status.Executed));
    }

    function test_MemoTooLongReverts() public {
        bytes memory big = new bytes(141);
        vm.prank(agent);
        vm.expectRevert(AgentVault.MemoTooLong.selector);
        vault.requestPayment(NATIVE, supplier, 1 ether, string(big));
    }

    // ---------------------------------------------------------------- validation humaine

    function test_QueuesAboveThreshold_ThenApprove() public {
        (AgentVault.Status s, uint256 id) = _pay(NATIVE, supplier, 4 ether);
        assertEq(uint256(s), uint256(AgentVault.Status.Queued));
        assertEq(supplier.balance, 0);
        vault.approve(id);
        assertEq(supplier.balance, 4 ether);
        assertEq(vault.openPending(), 0);
    }

    function test_ApproveCountsInDailySpend() public {
        (, uint256 id) = _pay(NATIVE, supplier, 4 ether);
        vault.approve(id);
        assertEq(vault.spentToday(NATIVE), 4 ether);
    }

    function test_RejectAndDoubleApproveFails() public {
        (, uint256 id) = _pay(NATIVE, supplier, 4 ether);
        vault.reject(id);
        vm.expectRevert(AgentVault.InvalidPending.selector);
        vault.approve(id);
        vm.expectRevert(AgentVault.InvalidPending.selector);
        vault.approve(99);
    }

    function test_ApproveRechecksRecipientAndPause() public {
        (, uint256 id) = _pay(NATIVE, supplier, 4 ether);
        vault.setRecipient(supplier, false);
        vm.expectRevert(AgentVault.InvalidPending.selector);
        vault.approve(id);
        vault.setRecipient(supplier, true);
        vault.setPaused(true);
        vm.expectRevert(AgentVault.InvalidPending.selector);
        vault.approve(id);
    }

    function test_PendingExpires() public {
        (, uint256 id) = _pay(NATIVE, supplier, 4 ether);
        vm.warp(block.timestamp + 3 days + 1);
        vm.expectRevert(AgentVault.PendingExpired.selector);
        vault.approve(id);
        vault.reject(id); // libère la place
        assertEq(vault.openPending(), 0);
    }

    function test_PendingSpamCapped() public {
        for (uint256 i; i < 10; i++) _pay(NATIVE, supplier, 3 ether);
        assertEq(uint256(_reason(NATIVE, supplier, 3 ether)), uint256(AgentVault.BlockReason.TooManyPending));
        // les petits paiements restent possibles
        (AgentVault.Status s,) = _pay(NATIVE, supplier, 1 ether);
        assertEq(uint256(s), uint256(AgentVault.Status.Executed));
    }

    // ---------------------------------------------------------------- nouvelles défenses

    function test_RecipientDelay_AntiRibChange() public {
        vault.setRecipientDelay(1 days);
        address newSupplier = makeAddr("newSupplier");
        vault.setRecipient(newSupplier, true);
        assertEq(uint256(_reason(NATIVE, newSupplier, 1 ether)), uint256(AgentVault.BlockReason.RecipientNotYetActive));
        vm.warp(block.timestamp + 1 days);
        (AgentVault.Status s,) = _pay(NATIVE, newSupplier, 1 ether);
        assertEq(uint256(s), uint256(AgentVault.Status.Executed));
    }

    function test_CanaryFreezesVault() public {
        vm.expectEmit(true, false, false, true);
        emit AgentVault.CanaryAlert(canary, 1 ether);
        (AgentVault.Status s,) = _pay(NATIVE, canary, 1 ether);
        assertEq(uint256(s), uint256(AgentVault.Status.Blocked));
        assertTrue(vault.paused());
        assertEq(uint256(_reason(NATIVE, supplier, 1 ether)), uint256(AgentVault.BlockReason.Paused));
    }

    function test_CircuitBreakerTripsAfterNBlocked() public {
        vault.setCircuitBreaker(3);
        _pay(NATIVE, attacker, 1 ether);
        _pay(NATIVE, attacker, 1 ether);
        assertFalse(vault.paused());
        vm.expectEmit(false, false, false, true);
        emit AgentVault.CircuitBreakerTripped(3);
        _pay(NATIVE, attacker, 1 ether);
        assertTrue(vault.paused());
        vault.setPaused(false);
        assertEq(vault.blockedToday(), 0);
    }

    function test_AgentKeyExpires() public {
        vault.setAgent(agent, uint64(block.timestamp + 1 hours));
        _pay(NATIVE, supplier, 1 ether);
        vm.warp(block.timestamp + 2 hours);
        assertEq(uint256(_reason(NATIVE, supplier, 1 ether)), uint256(AgentVault.BlockReason.AgentExpired));
    }

    function test_GuardianCanPauseButNotUnpause() public {
        vm.prank(guardian);
        vault.setPaused(true);
        assertTrue(vault.paused());
        vm.prank(guardian);
        vm.expectRevert(AgentVault.NotGuardian.selector);
        vault.setPaused(false);
        vm.prank(attacker);
        vm.expectRevert(AgentVault.NotGuardian.selector);
        vault.setPaused(true);
    }

    function test_AnchorReport() public {
        vm.expectEmit(true, false, false, true);
        emit AgentVault.ReportAnchored(keccak256("r"), "ipfs://x");
        vm.prank(guardian);
        vault.anchorReport(keccak256("r"), "ipfs://x");
        vm.prank(attacker);
        vm.expectRevert(AgentVault.NotGuardian.selector);
        vault.anchorReport(keccak256("r"), "");
    }

    // ---------------------------------------------------------------- contrôle d'accès

    function test_OnlyAgentCanRequest() public {
        vm.prank(attacker);
        vm.expectRevert(AgentVault.NotAgent.selector);
        vault.requestPayment(NATIVE, supplier, 1 ether, "x");
    }

    function test_AgentCannotChangePolicyOrWithdraw() public {
        vm.startPrank(agent);
        vm.expectRevert(AgentVault.NotOwner.selector);
        vault.setRecipient(attacker, true);
        vm.expectRevert(AgentVault.NotOwner.selector);
        vault.setLimits(NATIVE, 100 ether, 100 ether, 0);
        vm.expectRevert(AgentVault.NotOwner.selector);
        vault.withdraw(NATIVE, attacker, 1 ether);
        vm.expectRevert(AgentVault.NotOwner.selector);
        vault.approve(0);
        vm.expectRevert(AgentVault.NotOwner.selector);
        vault.setAgent(attacker, 0);
        vm.expectRevert(AgentVault.NotOwner.selector);
        vault.transferOwnership(attacker);
        vm.expectRevert(AgentVault.NotGuardian.selector);
        vault.setPaused(false);
        vm.stopPrank();
    }

    function test_TwoStepOwnership() public {
        address newOwner = makeAddr("newOwner");
        vault.transferOwnership(newOwner);
        assertEq(vault.owner(), address(this));
        vm.prank(attacker);
        vm.expectRevert(AgentVault.NotOwner.selector);
        vault.acceptOwnership();
        vm.prank(newOwner);
        vault.acceptOwnership();
        assertEq(vault.owner(), newOwner);
    }

    function test_ZeroAddressChecks() public {
        vm.expectRevert(AgentVault.ZeroAddress.selector);
        vault.setAgent(address(0), 0);
        vm.expectRevert(AgentVault.ZeroAddress.selector);
        vault.setRecipient(address(0), true);
        vm.expectRevert(AgentVault.ZeroAddress.selector);
        vault.withdraw(NATIVE, address(0), 1);
        vm.expectRevert(AgentVault.ZeroAddress.selector);
        new AgentVault(address(0));
    }

    function test_SetLimitsRejectsNonContractToken() public {
        vm.expectRevert(AgentVault.NotAContract.selector);
        vault.setLimits(address(0x1234), 1, 1, 0);
    }

    function test_WithdrawEmitsEvent() public {
        vm.expectEmit(true, true, false, true);
        emit AgentVault.Withdrawn(NATIVE, supplier, 1 ether);
        vault.withdraw(NATIVE, supplier, 1 ether);
    }

    function test_FalseReturningTokenReverts() public {
        FalseToken t = new FalseToken();
        vault.setLimits(address(t), 1e6, 1e6, 0);
        vm.prank(agent);
        vm.expectRevert(AgentVault.TransferFailed.selector);
        vault.requestPayment(address(t), supplier, 1, "x");
    }

    // ---------------------------------------------------------------- attaques

    function test_ReentrancyBlocked() public {
        ReentrantRecipient evil = new ReentrantRecipient();
        evil.setVault(vault);
        vault.setRecipient(address(evil), true);
        vault.setAgent(address(evil), 0); // pire cas : l'agent est le destinataire malveillant
        vm.prank(address(evil));
        vault.requestPayment(NATIVE, address(evil), 1 ether, "x");
        assertTrue(evil.reentered());
        assertFalse(evil.reentrySucceeded());
        assertEq(address(evil).balance, 1 ether);
    }

    function test_PausedBlocksEverything() public {
        vault.setPaused(true);
        (AgentVault.Status s,) = _pay(NATIVE, supplier, 1 ether);
        assertEq(uint256(s), uint256(AgentVault.Status.Blocked));
        assertEq(supplier.balance, 0);
    }

    // ---------------------------------------------------------------- fuzzing

    /// Quelle que soit la suite de montants demandés par un agent compromis, il ne dépasse jamais le plafond du jour.
    function testFuzz_NeverExceedsDailyLimit(uint96[12] calldata amounts) public {
        for (uint256 i; i < amounts.length; i++) {
            _pay(NATIVE, supplier, uint256(amounts[i]) % 6 ether);
        }
        assertLe(supplier.balance, 10 ether);
    }

    /// Un destinataire non autorisé ne reçoit jamais rien, quel que soit le montant.
    function testFuzz_AttackerNeverPaid(address to, uint256 amount) public {
        vm.assume(to != supplier && to != address(vault) && to.code.length == 0);
        uint256 before = to.balance;
        _pay(NATIVE, to, amount);
        assertEq(to.balance, before);
    }
}
