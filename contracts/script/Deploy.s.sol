// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {AgentVault} from "../src/AgentVault.sol";

/// Variables d'env :
///   PRIVATE_KEY (owner), AGENT_ADDRESS, SUPPLIER_ADDRESS                       obligatoires
///   FUND_WEI, CANARY_ADDRESS, NEW_SUPPLIER_ADDRESS, GUARDIAN_ADDRESS,
///   RECIPIENT_DELAY (s), AGENT_TTL (s), MAX_BLOCKED_PER_DAY                    optionnelles
contract Deploy is Script {
    function run() external {
        uint256 pk = vm.envUint("PRIVATE_KEY");
        address agent = vm.envAddress("AGENT_ADDRESS");
        address supplier = vm.envAddress("SUPPLIER_ADDRESS");
        uint256 fund = vm.envOr("FUND_WEI", uint256(0.5 ether));
        address canary = vm.envOr("CANARY_ADDRESS", address(0));
        address newSupplier = vm.envOr("NEW_SUPPLIER_ADDRESS", address(0));
        address guardian = vm.envOr("GUARDIAN_ADDRESS", address(0));
        uint64 delay = uint64(vm.envOr("RECIPIENT_DELAY", uint256(1 days)));
        uint64 ttl = uint64(vm.envOr("AGENT_TTL", uint256(30 days)));
        uint32 breaker = uint32(vm.envOr("MAX_BLOCKED_PER_DAY", uint256(5)));

        vm.startBroadcast(pk);
        AgentVault vault = new AgentVault(agent);
        // Fournisseur historique : actif tout de suite (ajouté avant d'activer le délai).
        vault.setRecipient(supplier, true);
        // AVAX : 0.1 max/tx, 0.3 /jour, validation humaine >= 0.05
        vault.setLimits(address(0), 0.1 ether, 0.3 ether, 0.05 ether);
        vault.setRecipientDelay(delay);
        // Nouveau fournisseur : payable seulement après le délai (démo anti « changement de RIB »).
        if (newSupplier != address(0)) vault.setRecipient(newSupplier, true);
        if (canary != address(0)) vault.setCanary(canary, true);
        if (guardian != address(0)) vault.setGuardian(guardian);
        vault.setCircuitBreaker(breaker);
        if (ttl != 0) vault.setAgent(agent, uint64(block.timestamp) + ttl);
        (bool ok,) = address(vault).call{value: fund}("");
        require(ok, "fund failed");
        vm.stopBroadcast();

        console.log("AgentVault deployed at:", address(vault));
        console.log("Deploy block:", block.number);
    }
}
