# Phase 5 Capability Matrix

日期：2026-06-14

## Purpose

This document records the generalized MVP eval surface used after Phase 5 eval adaptation. It gives reviewers a stable inventory of implemented cases and keeps the eval runner's coverage expectations visible in docs.

## Implemented Cases

| Case ID | Category | Capability | Policy Area |
|---------|----------|------------|-------------|
| `lookup_pending_order` | lookup | baseline | baseline |
| `cancel_pending_order` | cancel | baseline | baseline |
| `modify_pending_order_address` | modify_address | baseline | baseline |
| `return_delivered_order_item` | return | baseline | baseline |
| `exchange_delivered_order_item` | exchange | baseline | baseline |
| `transfer_to_human` | transfer | baseline | baseline |
| `deny_cancel_confirmation` | confirmation | baseline | baseline |
| `changed_confirmation_discards_pending_action` | confirmation | baseline | baseline |
| `block_cancel_processed_order` | guard | baseline | baseline |
| `block_return_pending_order` | guard | baseline | baseline |
| `block_wrong_user_order_access` | guard | baseline | baseline |
| `auth_name_zip_lookup_order` | auth | auth_name_zip | authentication |
| `modify_pending_order_items_success` | modify_items | modify_items | inventory |
| `modify_pending_order_payment_success` | modify_payment | modify_payment | payment_method |
| `modify_user_default_address_success` | modify_address | modify_user_address | user_profile |
| `multi_item_return_success` | return | multi_item_return | return_items |
| `multi_item_exchange_success` | exchange | multi_item_exchange | exchange_items |
| `deny_modify_payment_confirmation` | confirmation | modify_payment | confirmation |
| `changed_modify_items_confirmation` | confirmation | modify_items | confirmation |
| `block_item_product_mismatch` | guard | modify_items | inventory |
| `block_item_unavailable` | guard | modify_items | inventory |
| `block_payment_not_owned` | guard | modify_payment | payment_method |
| `block_payment_insufficient_gift_card` | guard | modify_payment | payment_method |
| `block_same_payment_method` | guard | modify_payment | payment_method |
| `block_modify_items_non_pending_order` | guard | modify_items | order_status |
| `block_modify_payment_processed_order` | guard | modify_payment | order_status |
| `block_exchange_product_mismatch` | guard | exchange_items | inventory |
| `block_exchange_unavailable_replacement` | guard | exchange_items | inventory |
| `transfer_unsupported_discount_request` | transfer | unsupported_request | transfer |
| `deny_modify_address_confirmation` | confirmation | modify_user_address | confirmation |

## Review Notes

- This matrix intentionally lists case IDs, not test function names. `tests/test_eval_runner.py` treats this document as a lightweight documentation contract.
- Baseline cases come from `curated_mvp`; generalized cases add coverage across authentication, inventory, payment, user profile, confirmation, transfer, and order-status policy areas.
- Future generalized cases should be added here in the same table when they become part of the stable `generalized_mvp` subset.
