# Phase 5 Capability Matrix

Date: 2026-06-12

This matrix defines the target capability surface for Phase 5. It is the bridge
between product behavior, tool coverage, guard rules, and eval cases.

## Matrix

| Capability | Intent | Required Slots | Tools | Guard Rules | Eval Coverage |
|---|---|---|---|---|---|
| Email authentication | existing auth path | email | `find_user_id_by_email`, `get_user_details` | no direct user id auth | existing curated regression |
| Name plus zip authentication | auth | first_name, last_name, zip | `find_user_id_by_name_zip`, `get_user_details` | all fields required, one active user per session | success, missing field, wrong identity |
| Order lookup | lookup | order_id | `get_order_details` | authenticated user owns order | success, wrong-user no-access |
| Cancel pending order | cancel_order | order_id, reason | `cancel_pending_order` | pending order, valid reason, ownership, read-before-write, confirmation | success, invalid status block, deny/change confirmation |
| Modify order shipping address | modify_order_address | order_id, address fields | `modify_pending_order_address` | pending-like order, ownership, read-before-write, confirmation | success, non-pending block, wrong-user block |
| Modify pending order items | modify_order_items | order_id, item_ids, new_item_ids | `modify_pending_order_items` | pending order, same product, replacement available, count match, ownership, confirmation | success, product mismatch block, unavailable block, count mismatch block |
| Modify pending order payment | modify_order_payment | order_id, payment_method_id | `modify_pending_order_payment` | pending-like order, payment owned by user, payment changed, gift card balance sufficient, confirmation | success, unowned payment block, same payment block, insufficient balance block |
| Modify user default address | modify_user_address | user_id or authenticated user, address fields | `modify_user_address` | target user is authenticated user, user context loaded, confirmation | success, wrong-user block, distinguish from order address |
| Return delivered items | return_items | order_id, item_ids, payment_method_id | `return_delivered_order_items` | delivered order, items in order, duplicate counts valid, payment owned by user, confirmation | single item success, multi-item success, non-delivered block |
| Exchange delivered items | exchange_items | order_id, item_ids, new_item_ids, payment_method_id | `exchange_delivered_order_items` | delivered order, old/new count match, same product, replacement available, payment owned by user, confirmation | single item success, multi-item success, product mismatch block, unavailable block |
| Transfer to human | transfer | summary | `transfer_to_human_agents` | explicit human request or unsupported capability | explicit human request, unsupported business request |
| Unsupported policy request | unknown or transfer | user message | optional transfer | no unexpected writes, clear refusal or transfer | discount, compensation, unsupported shipment request |

## Eval Subsets

`curated_mvp` remains the existing regression subset.

`generalized_mvp` should contain approximately 30 cases:

- 11 existing regression cases.
- 6-8 new success cases.
- 8-10 guard block cases.
- 3-4 confirmation/no-write cases.
- 2-3 unsupported or transfer cases.

## Implemented Cases

Current `generalized_mvp` contains these implemented cases, grouped by
capability:

- `auth_name_zip`: `auth_name_zip_lookup_order`
- `cancel`: `cancel_pending_order`
- `confirmation`: `deny_cancel_confirmation`, `changed_confirmation_discards_pending_action`
- `exchange`: `exchange_delivered_order_item`
- `exchange_items`: `block_exchange_product_mismatch`, `block_exchange_unavailable_replacement`
- `guard`: `block_cancel_processed_order`, `block_return_pending_order`, `block_wrong_user_order_access`
- `lookup`: `lookup_pending_order`
- `modify_address`: `modify_pending_order_address`
- `modify_items`: `modify_pending_order_items_success`, `changed_modify_items_confirmation`, `block_item_product_mismatch`, `block_item_unavailable`, `block_modify_items_non_pending_order`
- `modify_payment`: `modify_pending_order_payment_success`, `deny_modify_payment_confirmation`, `block_payment_not_owned`, `block_payment_insufficient_gift_card`, `block_same_payment_method`, `block_modify_payment_processed_order`
- `modify_user_address`: `modify_user_default_address_success`, `deny_modify_address_confirmation`
- `multi_item_exchange`: `multi_item_exchange_success`
- `multi_item_return`: `multi_item_return_success`
- `return`: `return_delivered_order_item`
- `transfer`: `transfer_to_human`
- `unsupported_request`: `transfer_unsupported_discount_request`

## Hard Acceptance Rules

- Deterministic `generalized_mvp` must pass before Phase 5 is considered done.
- Every write case must prove confirmation occurred before mutation.
- Every no-write case must preserve the DB hash.
- Every successful write must emit a write lock and audit log entry.
- User-facing responses may vary, but machine-readable guard reasons should stay
  stable for eval and dashboard use.
