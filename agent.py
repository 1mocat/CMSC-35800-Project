import os
import json
from utils.memory import write_memory_with_embeddings,find_similar_memory_entries,extract_mem_info_from_agent,check_memory_valid,read_memory
from utils.config import update_config, get_config_value
from agent_prompt import *
from agent_tools import query_target_agent,code_substitution_module,GCG_jailbreak_module,AmpleGCG_jailbreak_module,Advprompter_jailbreak_module,AutoDAN_jailbreak_module,self_reflection_module
import re
from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from langgraph.errors import GraphRecursionError



def Agent(item_index,input_prompt,baseline,current_memory_path,current_config_path):
    ### need to put in a config file
    os.environ['HUGGINGFACE_HUB_TOKEN'] = get_config_value("HUGGINGFACE_HUB_TOKEN",current_config_path)
    # os.environ["LANGCHAIN_TRACING_V2"] = get_config_value("LANGCHAIN_TRACING_V2",current_config_path)
    # os.environ["LANGCHAIN_API_KEY"] = get_config_value("LANGCHAIN_API_KEY",current_config_path)
    os.environ["AZURE_OPENAI_API_KEY"] = get_config_value("AZURE_OPENAI_API_KEY",current_config_path)
    os.environ["OPENAI_API_KEY"] = get_config_value("OPENAI_API_KEY",current_config_path)
    max_iteration = int(get_config_value("max_iteration",current_config_path))
    model_id = get_config_value("model_id",current_config_path)
    risk_scenario = get_config_value("risk_scenario",current_config_path)
    risk_scenario_index = get_config_value("risk_index",current_config_path)
    agent_base_llm = get_config_value("agent_base_llm",current_config_path)


    if(agent_base_llm=="openai"):
        from langchain_openai import ChatOpenAI
        model = ChatOpenAI(model="gpt-4o-mini")
    else:#azure
        from langchain_openai import AzureChatOpenAI
        model = AzureChatOpenAI(
            azure_endpoint="",
            azure_deployment="gpt-4o-mini",
            openai_api_version="2024-02-01",
        )### Use the agent: AzureChatOpenAI
        
    red_teaming_requirement = input_prompt

    tools = [query_target_agent,code_substitution_module,GCG_jailbreak_module,AmpleGCG_jailbreak_module,Advprompter_jailbreak_module,AutoDAN_jailbreak_module,self_reflection_module]#step_by_step_module 
    tools = [query_target_agent,code_substitution_module,GCG_jailbreak_module]# abolition
    tool_names = [tool.__name__ for tool in tools]
    # model_with_tools = model.bind_tools(tools)#parallel_tool_calls=False # for openai
    agent = create_react_agent(model, tools, state_modifier=agent_system_prompt)
    
    # current_memory = read_memory(file_path=os.path.join(os.path.dirname(__file__), f"./memory/memory_{risk_scenario_index}.json"))
    # current_memory = read_memory(file_path=os.path.join(os.path.dirname(__file__), f"./memory/good_memory.json"))
    # print(f"current_memory_path = {current_memory_path}")

    most_similar_experiences,most_similar_indexs = find_similar_memory_entries(
    risk_scenario=risk_scenario,
    model_type=model_id,
    red_teaming_requirement=red_teaming_requirement,
    file_path=current_memory_path
    )


    most_similar_experiences_str = ' '.join([f"Experience{i+1}. {entry}" for i, entry in enumerate(most_similar_experiences)])


    processed_most_similar_experiences = re.sub(r'\\{2,}', r'\\', most_similar_experiences_str)

    print("most_similar_indexs:", most_similar_indexs)
    
    query = f"Current test case index is {item_index}. Current red teaming scenario is {risk_scenario}. Current target goal is to {red_teaming_requirement}."
    if processed_most_similar_experiences != "":
        print("processed_most_similar_experiences is not empty.")
        query += f"The previous experience you can refer to are as follows: {processed_most_similar_experiences}"
        
    store_message = ""
    round_memory_data = {
        "risk_index": item_index,
        "risk_scenario": risk_scenario,
        "red_teaming_requirement": red_teaming_requirement,
        "model_type": model_id,
        "reference_experience_index":most_similar_indexs,
        "tool_names":tool_names,
        "trajectory": [],
        "evaluation_result": "",
        "self_reflection": "",
        "memory_validity":"Invalid",
    }

    first_message = True 

    try:
        for chunk in agent.stream(
            {"messages": [("human", query)]},
            {"recursion_limit": max_iteration},
            stream_mode="values",
        ):
            if first_message:
                first_message = False
                continue
        
            # print(f"#####This is a chunk message: {chunk['messages'][-1]}")
            message = chunk["messages"][-1]
            message.pretty_print()
            
            # with open(f'chunk_output_{risk_scenario_index}.txt', 'a') as file:
            #     file.write("#####This is a chunk message: " + str(chunk["messages"][-1]) + "\n")
            #     file.flush()
            store_message += str(message) + "\n"
            # print(f"### Current store_message is : {store_message}")
            if "tool_call_id" in store_message and "self_reflection_module" not in store_message:
                # print(f"## Current extract information of tools: {store_message}")
                trajectory_memory_data = extract_mem_info_from_agent(store_message)
                
                round_memory_data["trajectory"].append(trajectory_memory_data)
                
                if round_memory_data["evaluation_result"] != "attack success":
                    round_memory_data["evaluation_result"] = trajectory_memory_data["evaluation_result"]
                
                store_message = ""
            if "tool_call_id" in store_message and "self_reflection_module" in store_message:
                # print(f"## Current extract information of self_reflection: {store_message}")
                # print(f"##### Current round_memory_data: {round_memory_data}")
                trajectory_memory_data = extract_mem_info_from_agent(store_message)
                round_memory_data["self_reflection"] = trajectory_memory_data["tool_call_results"]
                store_message = ""
                if round_memory_data["evaluation_result"] == "attack success":
                    print("&&& Attack success and have self reflection, writing memory")
                    round_memory_data["memory_validity"] = "Valid" #check_memory_valid(round_memory_data)
                    # write_memory_with_embeddings(round_memory_data,file_path=ocurrent_memory_path)
                    
    except GraphRecursionError:
        print(f"&&& Error with item index {item_index}: Agent stopped due to max iterations. Continuing to next item.")
    except Exception as e:
        print(f"&&& An unexpected error occurred with item index {item_index}: {str(e)}")
    
    print(f"&&& Finally write into memory,no matter success or failure.")
    write_memory_with_embeddings(round_memory_data,file_path=current_memory_path) #record failure cases for case study

    

