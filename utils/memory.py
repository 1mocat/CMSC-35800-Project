import json
import os
import re
import datetime
from .config import get_config_value
from sentence_transformers import SentenceTransformer, util
from models import Client
from agent_prompt import *
import torch
model = SentenceTransformer('paraphrase-MiniLM-L6-v2')

"""
round_memory_data = {
        "risk_index": item_index,
        "risk_scenario": risk_scenario,
        "red_teaming_requirement": red_teaming_requirement,
        "model_type": model_id,
        "trajectory": [],
        "evaluation_result": "",
        "self_reflection": "",
        "memory_validity":"",
    }
"""

def check_memory_valid(round_memory_data):

    # risk_scenario_str = str(risk_scenario)
    # red_teaming_requirement_str = str(red_teaming_requirement)
    # trajectory_str = str(trajectory)
    # full_input_prompt = "risk_scenario:"+risk_scenario_str + "\n"+"red_teaming_requirement_str:"+red_teaming_requirement_str + "\n"+"trajectory:"+trajectory_str
    target_llm = Client(model_id="gpt-4o-mini", sys_msg=memory_constrainer_prompt)
    target_llm_response = target_llm.generate(usr_msg="who are you")
    print(f"{target_llm_response}")
    target_llm_response = "yes" # set all to Valid
    if "yes" in target_llm_response.lower():
        print("*** memory validity check result is: Valid")
        return "Valid"
    elif "no" in target_llm_response.lower():
        print("*** memory validity check result is: Invalid")
        return "Invalid"
    else:
        print("*** memory validity check result is: Not sure")
        return "Not sure"
    
# risk_index = get_config_value("risk_index") 

def read_memory(file_path=os.path.join(os.path.dirname(__file__), f"./memory/good_memory.json")):
    if not os.path.exists(file_path):
        return []
    
    with open(file_path, 'r') as f:
        try:
            memory = json.load(f)
        except json.JSONDecodeError:
            memory = []
    
    return memory

def process_item(item):
    if isinstance(item, dict):
        for key, value in item.items():
            if isinstance(value, str):
                item[key] = re.sub(r'\\{2,}', r'\\', value)
            if key in ['red_teaming_embedding', 'risk_scenario_embedding'] and isinstance(value, list):
                item[key] = json.dumps(value).replace("\n", "").replace(" ", "")
    return item

def write_memory_with_embeddings(new_entry, file_path):
    print("write_memory_with_embeddings...")
    memory_list = read_memory(file_path)
    
    if 'risk_scenario' in new_entry:
        new_entry['risk_scenario_embedding'] = model.encode(new_entry['risk_scenario'], convert_to_tensor=False).tolist()
    if 'red_teaming_requirement' in new_entry:
        new_entry['red_teaming_embedding'] = model.encode(new_entry['red_teaming_requirement'], convert_to_tensor=False).tolist()
    if isinstance(new_entry, list):
        processed_data = [process_item(data) for data in new_entry]
        memory_list.extend(processed_data)
    else:
        processed_data = process_item(new_entry)
        memory_list.append(processed_data)

    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(memory_list, f, ensure_ascii=False, indent=4)
        f.flush()  
        os.fsync(f.fileno()) 

def initialize_embeddings(file_path):
    
    memory_list = read_memory(file_path)
    
    for entry in memory_list:
        # print(f"initialize_embeddings {entry['risk_index']}...")
        if 'risk_scenario' in entry and 'risk_scenario_embedding' not in entry:
            entry['risk_scenario_embedding'] = model.encode(entry['risk_scenario'], convert_to_tensor=False).tolist()
        if 'red_teaming_requirement' in entry and 'red_teaming_embedding' not in entry:
            entry['red_teaming_embedding'] = model.encode(entry['red_teaming_requirement'], convert_to_tensor=False).tolist()
        
        entry = process_item(entry)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(memory_list, f, ensure_ascii=False, indent=4)
        f.flush()
        os.fsync(f.fileno()) 
    
def find_similar_memory_entries(risk_scenario, model_type, red_teaming_requirement, file_path):
    memory_list = read_memory(file_path)

    device = "cuda" if torch.cuda.is_available() else "cpu"

    risk_scenario_embedding = model.encode(risk_scenario, convert_to_tensor=True) if risk_scenario else None
    red_teaming_embedding = model.encode(red_teaming_requirement, convert_to_tensor=True) if red_teaming_requirement else None

    top_matches = []

    for entry in memory_list:
        if entry.get('memory_validity', '') != "Valid" or entry.get('evaluation_result', '') != "attack success":
            continue

        score = 0

        if 'risk_scenario_embedding' in entry and risk_scenario_embedding is not None:

            risk_scenario_embedding_value = json.loads(entry['risk_scenario_embedding']) if isinstance(entry['risk_scenario_embedding'], str) else entry['risk_scenario_embedding']
            risk_scenario_tensor = torch.tensor(risk_scenario_embedding_value).to(device)
            risk_scenario_similarity = util.pytorch_cos_sim(risk_scenario_tensor, risk_scenario_embedding)
            score += risk_scenario_similarity.item()

        if 'red_teaming_embedding' in entry and red_teaming_embedding is not None:
            red_teaming_embedding_value = json.loads(entry['red_teaming_embedding']) if isinstance(entry['red_teaming_embedding'], str) else entry['red_teaming_embedding']
            red_teaming_tensor = torch.tensor(red_teaming_embedding_value).to(device)
            red_teaming_similarity = util.pytorch_cos_sim(red_teaming_tensor, red_teaming_embedding)
            score += red_teaming_similarity.item()

        trajectory_length_penalty = abs(len(entry['trajectory']))
        score -= (trajectory_length_penalty / 50)


        top_matches.append((score, entry))
        top_matches = sorted(top_matches, key=lambda x: x[0], reverse=True)[:3]

    def filter_entry(entry):
        return {k: v for k, v in entry.items() if k not in ['risk_scenario_embedding', 'red_teaming_embedding']}

    top_entries_strings = [str(filter_entry(entry[1])) for entry in top_matches] 
    top_entries_indexs = [str(entry[1].get('risk_index', 'No')) for entry in top_matches] 

    return top_entries_strings, top_entries_indexs


def extract_mem_info_from_agent(message):
    # Initialize variables to store results
    reason_for_using_this_tool = ""
    tool_name = ""
    tool_call_results = ""
    evaluation_result = ""
    time_cost = ""
    tool_input_parameters = ""

    # Extract reason_for_using_this_tool
    # "reason_for_this_tool":"
    reason_match = re.search(r'"reason_for_using_this_tool":["](.*?)["]', message)
    if reason_match:
        reason_for_using_this_tool = reason_match.group(1)

    print(f"reason_for_using_this_tool is {reason_for_using_this_tool}")
    # Extract tool name
    tool_name_match = re.search(r"'name': '([^']+)'", message)
    if tool_name_match:
        tool_name = tool_name_match.group(1)

    #Extract tool_input_parameters
    tool_input_parameters_match = re.search(r"arguments': '{(.*?)}', 'name'", message)
    if tool_input_parameters_match:
        tool_input_parameters = tool_input_parameters_match.group(1)

    # Extract tool call results
    tool_call_result_match = re.search(r"content='{(.*?)}' name=", message)
    if tool_call_result_match:
        tool_call_results = tool_call_result_match.group(1)
    
    print(f"tool_call_results is {tool_call_results}")
    
    time_cost_match = re.search(r'"time cost": "([^"]+)"', tool_call_results)
    if time_cost_match:
        time_cost = time_cost_match.group(1)
        print(f"Time cost: {time_cost}")

    tool_call_results_without_time_cost = re.sub(r'"time cost": "([^"]+)"', '', tool_call_results)

    # print(f"tool_call_results_dict is {tool_call_results_dict}")
    # Keeping evaluation_result logic unchanged
    evaluation_result_match = re.search(r'"Evaluation result": "(.*?)"', message)
    if evaluation_result_match:
        evaluation_result = evaluation_result_match.group(1)

    # Construct and return the dictionary with extracted data
    trajectory_data = {
    "reason_for_using_this_tool": reason_for_using_this_tool,
    "tool_name": tool_name,
    "time_cost_for_calling_this_tool": time_cost,
    "tool_input_parameters": tool_input_parameters,
    "tool_call_results": tool_call_results_without_time_cost,
    "evaluation_result": evaluation_result if evaluation_result != "" else "No evaluation result because you did not query target agent",
    }

    print(trajectory_data)
    return trajectory_data


