from unittest.mock import patch

from app.agent.nodes.act import act_graph_node

LOOP_RESULT = {"final_response": "Risposta dell'agent loop", "execution_trace": []}


def test_plan_request_without_plan_goes_to_agent_loop():
    # Senza plan_structure nel thread non si inventa un esito: decide l'agent loop con tool reali
    state = {"task": "Esegui il piano per: crea CT; configura DNS", "execute": True}
    with patch("app.agent.nodes.act.run_agent_loop", return_value=LOOP_RESULT) as loop, \
         patch("app.agent.nodes.act.execute_plan") as execute_plan:
        res = act_graph_node(state)

    loop.assert_called_once()
    execute_plan.assert_not_called()
    assert res["final_response"] == "Risposta dell'agent loop"
    assert "Eseguito con successo" not in res["plan"]["direct_answer"]


def test_execute_flag_with_plan_runs_the_plan():
    plan_structure = {"steps": [{"id": 1, "tool": "proxmox-mcp__list_containers", "args": {}}]}
    state = {"task": "Esegui il piano per: lista container", "execute": True, "plan_structure": plan_structure}
    with patch("app.agent.nodes.act.run_agent_loop") as loop, \
         patch("app.agent.nodes.act.execute_plan", return_value={"final_response": "piano eseguito"}) as execute_plan:
        res = act_graph_node(state)

    loop.assert_not_called()
    assert execute_plan.call_args.args[0] == plan_structure
    assert res["final_response"] == "piano eseguito"
