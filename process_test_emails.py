import time
from uuid import UUID
from app.workflows.pipeline import understand_step, resolve_step, link_step, propose_step, done_step

items = [
    ("Maintenance Email (suryanshtyagi.work@gmail.com)", "01a1439e-7693-7e10-88d4-39ff002da5e9"),
    ("Payment Email (vipint9902@gmail.com)", "01a1439e-7624-7163-9807-1a50274721e8"),
    ("Lease Email (fino332222@gmail.com)", "01a1439e-72c0-7773-adbf-cf05c76724b2"),
]

for label, mid in items:
    print(f"\n==========================================")
    print(f"Processing {label}: {mid}")
    print(f"==========================================")
    
    # 1. UNDERSTANDING AGENT
    print("[1/4] Running UNDERSTANDING agent...")
    u_res = understand_step(mid)
    print(f"   -> Result: {u_res}")
    time.sleep(2)

    # 2. RESOLVE SENDER (Directory)
    print("[2/4] Resolving sender identity...")
    resolve_step(mid)
    
    # 3. LINKING (LINK_CHECK / CASE_SUMMARY AGENT)
    print("[3/4] Linking message to Case...")
    case_id = link_step(mid)
    print(f"   -> Linked Case ID: {case_id}")
    time.sleep(2)

    # 4. PROPOSER AGENT (Multi-Draft generation)
    if case_id:
        print("[4/4] Running PROPOSER agent for multi-drafts...")
        p_res = propose_step(mid)
        print(f"   -> Generated Approvals: {p_res['approval_ids']}")
        print(f"   -> Exceptions: {p_res['exceptions']}")
        done_step(mid)
        print("   -> Pipeline marked done.")

    print("Waiting 15 seconds before next message to respect Gemini API rate limits...")
    time.sleep(15)

print("\nALL 3 TEST MESSAGES PROCESSED THROUGH AGENTS SUCCESSFULLY!")
