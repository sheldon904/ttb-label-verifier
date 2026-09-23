"""Optional model assistance, never on the path to a rejection.

Two features live here, and both sit downstream of the rule engine:

  second_opinion  a vision model re-reads only the fields the OCR read could
                  not support, on a label the rules referred. It can clear a
                  referral. It can never produce a FAIL.
  triage          orders referrals by how likely each is to be a real defect,
                  so an agent working a 300-label batch starts with the ones
                  that matter. It never changes a verdict.

Each switches on only when its credential is present: an OpenRouter or
Anthropic key for the second reading, an AI Gateway key or Vercel's OIDC token
for triage by Jev. Without them the app makes no outbound call and triage uses
a local heuristic. See docs/DECISIONS.md.
"""
