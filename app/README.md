# app/ — the "drop" target (Phase 1)

The thing we defend: a tiny limited-stock store (Lambda + API Gateway + DynamoDB) with a
`/products` listing and a `/checkout` race. Deployed by Terraform in `infra/`. Built in Phase 1.

## API behavior

- Start with `GET /products` and retain the returned `session_id` cookie. It is Secure,
  HttpOnly, SameSite=Lax, with a one-hour lifetime. Unknown or expired session IDs rotate
  to a server-generated ID; these are anonymous shopping sessions, not user accounts.
- `POST /cart` accepts `{ "product_id": "..." }`. Inventory decrement and reservation
  creation commit together. Retrying cart is a new reservation, so clients must not
  blindly retry an ambiguous successful cart response.
- `POST /checkout` accepts `{ "reservation_id": "..." }`. Consumption and order creation
  commit together. Repeating checkout for the same reservation and session returns the
  same order ID, including after reservation cleanup. A transaction conflict returns 409
  and can be retried. Expired unconsumed reservations return 410.
- Invalid JSON, missing identifiers and invalid reset products return 400. Admin reset
  validates the complete supplied product list before clearing orders/reservations.
- Catalog listing consumes all DynamoDB query pages. Reservation stock reclamation
  remains deferred: reset inventory between experiments.
- When `ORIGIN_SECRET` is configured, the authorizer rejects requests without matching
  `X-Origin-Verify` before session access. Terraform supplies the secret at CloudFront.
- Application logs contain SHA-256 session digests under `session_id`, never raw cookie
  tokens. Apply the same digest when correlating independently generated labels.

## Local verification

From `app/`, run `python -m pytest -q`. The Moto suite covers transaction rollback,
overlapping checkout requests, session cookies/expiry, origin checks and invalid inputs.
Deployed CloudFront/API Gateway behavior still needs an explicit cloud smoke test.
