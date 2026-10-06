// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AgentVault} from "../src/AgentVault.sol";

/// Agent compromis : le fuzzer appelle ces fonctions au hasard, des milliers de fois, dans n'importe quel ordre.
contract CompromisedAgent is Test {
    AgentVault public vault;
    address public agent;
    address public supplier;
    address[] public targets;
    uint256 public paidOutsideAllowlist;

    constructor(AgentVault v, address a, address s) {
        vault = v;
        agent = a;
        supplier = s;
        targets.push(s);
        targets.push(makeAddr("attacker1"));
        targets.push(makeAddr("attacker2"));
    }

    function pay(uint256 who, uint256 amount, string calldata memo) external {
        if (bytes(memo).length > 140) return;
        address to = targets[who % targets.length];
        uint256 before = to.balance;
        vm.prank(agent);
        vault.requestPayment(address(0), to, amount % 3 ether, memo);
        if (to != supplier && to.balance > before) paidOutsideAllowlist++;
    }

    function tryAdmin(uint256 which) external {
        vm.startPrank(agent);
        if (which % 4 == 0) try vault.setRecipient(targets[1], true) {} catch {}
        if (which % 4 == 1) try vault.setLimits(address(0), 100 ether, 100 ether, 0) {} catch {}
        if (which % 4 == 2) try vault.withdraw(address(0), targets[1], 1 ether) {} catch {}
        if (which % 4 == 3) try vault.setPaused(false) {} catch {}
        vm.stopPrank();
    }

    function nextDay() external {
        vm.warp(block.timestamp + 1 days);
    }
}

contract AgentVaultInvariantTest is Test {
    AgentVault vault;
    CompromisedAgent handler;
    address agent = makeAddr("agent");
    address supplier = makeAddr("supplier");
    uint256 startDay;

    function setUp() public {
        vm.warp(1_760_000_000);
        vault = new AgentVault(agent);
        vm.deal(address(vault), 1_000 ether);
        vault.setRecipient(supplier, true);
        vault.setLimits(address(0), 1 ether, 2 ether, 0.8 ether);
        vault.setCanary(makeAddr("canary"), true);
        vault.setCircuitBreaker(50);
        handler = new CompromisedAgent(vault, agent, supplier);
        targetContract(address(handler));
        startDay = block.timestamp / 1 days;
    }

    /// Jamais un centime vers une adresse hors liste blanche.
    function invariant_NoPaymentOutsideAllowlist() public view {
        assertEq(handler.paidOutsideAllowlist(), 0);
    }

    /// Dépense totale <= plafond journalier x nombre de jours écoulés (aucun paiement en attente n'est validé ici).
    function invariant_SpendBoundedByDailyLimit() public view {
        uint256 days_ = block.timestamp / 1 days - startDay + 1;
        assertLe(supplier.balance, 2 ether * days_);
    }

    /// L'agent ne peut jamais modifier la configuration.
    function invariant_PolicyUnchanged() public view {
        (uint128 maxPerTx, uint128 daily,) = vault.limits(address(0));
        assertEq(maxPerTx, 1 ether);
        assertEq(daily, 2 ether);
        assertEq(vault.owner(), address(this));
        assertEq(vault.agent(), agent);
    }

    /// Le nombre de paiements en attente reste borné (anti-spam).
    function invariant_PendingBounded() public view {
        assertLe(vault.openPending(), vault.MAX_OPEN_PENDING());
    }
}
