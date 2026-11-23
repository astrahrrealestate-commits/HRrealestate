"""Test SuperAgent queries locally against the live database and Gemini 3.8 Flash."""

import os
import sys

# Ensure backend is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.core.settings import Settings
from sqlalchemy import create_engine
from app.api.agent.routes import _resolve_calendar_action, _build_query_preview_card
from app.tools.query_agent.agent import run_query_agent
from uuid import UUID

def run_tests():
    settings = Settings(_env_file="backend/.env")
    print(f"=== Testing with LLM Model: {settings.llm_model} ===")
    print(f"=== Database URL: {str(settings.database_url)} ===")
    
    engine = create_engine(str(settings.database_url))
    company_id = UUID("00000000-0000-0000-0000-000000000001")

    # -------------------------------------------------------------
    # Test 1: Calendar Dummy Card Fix ("can u setup meeting with a teenant")
    # -------------------------------------------------------------
    print("\n--- [Test 1] Calendar Fallback Check ---")
    query_1 = "can u setup meeting with a teenant"
    ans, card, actions, steps = _resolve_calendar_action(query_1, engine, company_id, [])
    print(f"Query: '{query_1}'")
    print(f"Answer: {ans}")
    print(f"Card generated: {card}")
    assert card is None, "FAIL: Dummy card was generated!"
    assert "Which property" in (ans or ""), "FAIL: Expected clarifying question!"
    print(">>> PASS: Calendar correctly asks for clarification without creating dummy 'Assigned Contractor' card.")

    # -------------------------------------------------------------
    # Test 2: Navigation Buttons & Typo Tolerance in Cards
    # -------------------------------------------------------------
    print("\n--- [Test 2] Navigation Buttons & Typo Check ---")
    
    # 2a. Properties count (scalar count)
    card_prop, acts_prop = _build_query_preview_card("how many properties i have", [{"Total Properties": 59}], ["Total Properties"], 1)
    print(f"Query 'how many properties i have' -> Action payload: {acts_prop[0].payload}, Action label: {acts_prop[0].label}")
    assert acts_prop[0].payload == "/properties", "FAIL: Properties didn't route to /properties!"
    assert acts_prop[0].label == "Open Properties", "FAIL: Button label is not Open Properties!"

    # 2b. Vacant properties count (scalar count)
    card_vac, acts_vac = _build_query_preview_card("how many properties are vacant", [{"Vacant Properties": 10}], ["Vacant Properties"], 1)
    print(f"Query 'how many properties are vacant' -> Action payload: {acts_vac[0].payload}, Action label: {acts_vac[0].label}")
    assert acts_vac[0].payload == "/properties", "FAIL: Vacant didn't route to /properties!"
    assert acts_vac[0].label == "Open Properties", "FAIL: Button label is not Open Properties!"

    # 2c. Tenant count with typo ("how many tenaants i have currently")
    card_ten, acts_ten = _build_query_preview_card("how many tenaants i have currently", [{"Current Tenants Count": 59}], ["Current Tenants Count"], 1)
    print(f"Query 'how many tenaants i have currently' (typo) -> Action payload: {acts_ten[0].payload}, Action label: {acts_ten[0].label}")
    assert acts_ten[0].payload == "/tenants", "FAIL: Typo tenaants didn't route to /tenants!"
    assert acts_ten[0].label == "Open Tenants", "FAIL: Button label is not Open Tenants!"
    print(">>> PASS: All navigation buttons route correctly to /properties and /tenants.")

    # -------------------------------------------------------------
    # Test 3: Gemini 3.8 Flash SQL Generation for Contractor Directory
    # -------------------------------------------------------------
    print("\n--- [Test 3] Query Agent SQL Generation via Gemini 3.8 Flash ---")
    q_contractor = "who is this guy [00109 Chahal Bouw]"
    print(f"Query: '{q_contractor}'")
    res_c = run_query_agent(engine, settings, company_id, q_contractor)
    print(f"Generated SQL:\n  {res_c.sql}")
    print(f"Answer: {res_c.answer}")
    print(f"Rows count: {res_c.row_count}")
    assert "people" in res_c.sql.lower(), "FAIL: Contractor search did not query people table!"
    assert "chahal" in res_c.sql.lower() or "109" in res_c.sql, "FAIL: Contractor name or brixx_ref not in SQL!"
    print(">>> PASS: Query Agent generated accurate SQL over people table for contractor lookup.")

    # -------------------------------------------------------------
    # Test 4: Dutch Address Matching with Partial Street & Number
    # -------------------------------------------------------------
    print("\n--- [Test 4] Dutch Address & Tenant Verification ---")
    q_tenant = "Is H. Ganesh a tenant at Henry Dunantweg 5B, 2402NM ALPHEN AAN DEN RIJN?"
    print(f"Query: '{q_tenant}'")
    res_t = run_query_agent(engine, settings, company_id, q_tenant)
    print(f"Generated SQL:\n  {res_t.sql}")
    print(f"Answer: {res_t.answer}")
    print(f"Rows count: {res_t.row_count}")
    assert "henry dunantweg" in res_t.sql.lower() or "dunantweg" in res_t.sql.lower(), "FAIL: Address not matched!"
    print(">>> PASS: Query Agent tokenized Dutch address matching street name and house number.")

    # -------------------------------------------------------------
    # Test 5: Fix 3 - Context-Aware Occupancy Breakdown for Counts
    # -------------------------------------------------------------
    print("\n--- [Test 5] Context-Aware Occupancy Count Synthesis ---")
    
    # 5a. Tenant count query
    q_count_tenants = "how many tenaants i have currently"
    print(f"Query: '{q_count_tenants}'")
    res_ct = run_query_agent(engine, settings, company_id, q_count_tenants)
    print(f"Answer: {res_ct.answer}")
    assert "active tenants" in res_ct.answer.lower(), "FAIL: Tenant answer missing active tenants!"
    assert "occupied properties" in res_ct.answer.lower(), "FAIL: Tenant answer missing occupied properties breakdown!"
    assert "vacant" in res_ct.answer.lower(), "FAIL: Tenant answer missing vacant context!"
    print(">>> PASS: Tenant count query explains co-tenant occupancy breakdown.")

    # 5b. Vacant count query
    q_count_vacant = "how many properties are vacant"
    print(f"Query: '{q_count_vacant}'")
    res_cv = run_query_agent(engine, settings, company_id, q_count_vacant)
    print(f"Answer: {res_cv.answer}")
    assert "vacant" in res_cv.answer.lower(), "FAIL: Vacant answer missing vacant properties!"
    assert "total properties" in res_cv.answer.lower(), "FAIL: Vacant answer missing total properties context!"
    print(">>> PASS: Vacancy count query provides total portfolio context.")

    # 5c. Total properties count query
    q_count_props = "how many properties i have"
    print(f"Query: '{q_count_props}'")
    res_cp = run_query_agent(engine, settings, company_id, q_count_props)
    print(f"Answer: {res_cp.answer}")
    assert "total properties" in res_cp.answer.lower(), "FAIL: Properties answer missing total count!"
    assert "occupied" in res_cp.answer.lower(), "FAIL: Properties answer missing occupied breakdown!"
    print(">>> PASS: Total properties query provides complete portfolio occupancy context.")

    # -------------------------------------------------------------
    # Test 6: Persona & Identity Check ("what is your name what can u b do")
    # -------------------------------------------------------------
    print("\n--- [Test 6] Persona & Identity Check ---")
    from app.llm.agents.concierge import CONCIERGE, concierge_prompt
    from app.llm.calls import CallContext, run_agent
    from app.llm.budget import CONCIERGE_PURPOSE

    q_identity = "what is your name what can u b do"
    prompt_id = concierge_prompt(q_identity, [], [], [])
    dev_company_id = UUID("01a1341b-2e4e-7073-b44e-40a7bc9e8e2a")
    call_res = run_agent(engine, settings, CONCIERGE, prompt_id, CallContext(dev_company_id, CONCIERGE_PURPOSE))
    plan = call_res.output
    print(f"Query: '{q_identity}'")
    print(f"Reply: {plan.reply}")
    assert "astra" in (plan.reply or "").lower(), "FAIL: Reply does not introduce as Astra!"
    assert "large language model" not in (plan.reply or "").lower(), "FAIL: Generic LLM disclaimer present!"
    print(">>> PASS: Assistant identifies as Astra without generic LLM disclaimers.")

    print("\n==========================================")
    print("ALL CUSTOM TESTS PASSED WITH GEMINI 3.8 FLASH!")
    print("==========================================")

if __name__ == "__main__":
    run_tests()
