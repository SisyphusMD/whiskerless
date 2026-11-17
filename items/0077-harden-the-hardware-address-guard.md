# #77 Harden the hardware-address guard

- Kind: pull, state: closed, by cody, created 2026-08-28T22:30:55-07:00
- Labels: none; milestone: none
- refs/pull/77/head -> main, merged: True

Follow-ups to the guard added with the audit fixes, all found by review:

- hyphen and Cisco-dotted spellings were not matched at all
- a fixed six-group pattern read the tail of an IPv6 address written with variable-width hextets as an address, and the head of a longer byte run such as 01-02-...-08
- a short hex-looking label glued to the front (id:, or the trailing letters of mac:) made the whole token fail the two-digit test and vanish

Now: maximal run per separator, judged by shape. Six two-digit groups is an address; seven is a label glued to one and is ambiguous about which end, so both readings are offered and the allowlist decides; eight or more is a byte sequence or IPv6. Bare packed hex is deliberately NOT matched — the sibling tree carries 156 distinct twelve-hex tokens, so that rule would fail every run and the guard would be deleted.
