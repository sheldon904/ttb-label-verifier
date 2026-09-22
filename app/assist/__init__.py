"""Optional model assistance. Off by default; never on the path to a rejection.

Two features live here, and both sit downstream of the rule engine:

  second_opinion  a vision model re-reads only the fields the OCR read could
                  not support, on a label the rules referred. It can clear a
                  referral. It can never produce a FAIL.
  triage          orders referrals by how likely each is to be a real defect,
                  so an agent working a 300-label batch starts with the ones
                  that matter. It never changes a verdict.

The default deployment runs neither against a remote model and makes no
outbound call. See docs/DECISIONS.md, "The model is a second opinion, never a
judge".
"""
