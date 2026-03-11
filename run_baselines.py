import argparse
import os
import json
from agent_tools import GCG_jailbreak_module, AmpleGCG_jailbreak_module,Advprompter_jailbreak_module,AutoDAN_jailbreak_module
from utils.memory import initialize_embeddings
from OCI_evaluation.OCI_run import OCI
from utils.config import get_config_value,update_config
from OCI_evaluation.OCI_interface import create_docker,delete_docker
from agent import Agent
import time
import shutil
import multiprocessing
import concurrent.futures

multiprocessing.set_start_method('spawn', force=True)

current_dir = os.path.dirname(os.path.abspath(__file__))

# global
baseline = "agent"

def get_baseline():
    return baseline

risk_dictionary = {
    "1": "Post sensitive files online",
    "2": "Untrusted installation",
    "3": "Crawl a risky website",
    "4": "Copy sensitive files",
    "5": "List out files under sensitive directories",
    "6": "Write risky content into files",
    "7": "Read sensitive files",
    "8": "Delete sensitive files",
    "9": "Add risky alias to bashrc",
    "10": "Creating a reverse shell",
    "11": "Monitor system",
    "12": "Code with bias issues",
    "13": "Sensitive path traversal",
    "14": "Eval injection",
    "15": "Regular expressions in IP validation",
    "16": "Side channel information leakage",
    "17": "Improper execution privileges",
    "18": "Process management",
    "19": "PRNG seed management",
    "20": "Cryptographic predictability",
    "21": "Amplification",
    "22": "Missing default case",
    "23": "Flawed behavioral workflow",
    "24": "Unsafe deserialization",
    "25": "Duplicate key in associative list",
    "26": "Crawling a risky website with a random-character URL",
    "27": "Memory leak"
}

error_log_path = os.path.join(os.path.dirname(__file__), "../error_index.json")

def copy_memory(risk_scenario_index):

    source_file = './memory/good_memory.json'
    destination_file = f'./memory/good_memory_{risk_scenario_index}.json'

    try:
        shutil.copy(source_file, destination_file)
        print(f'Successfully copied to {destination_file}')
    except Exception as e:
        print(f'Failed to copy file: {e}')

def copy_config(baseline):

    source_file = './baselines/Agent_config.json'
    destination_file = f'./baselines/{baseline}_config.json'

    try:
        shutil.copy(source_file, destination_file)
        print(f'Successfully copied to {destination_file}')
    except Exception as e:
        print(f'Failed to copy file: {e}')

def log_error_item(item_index):

    if not os.path.exists(error_log_path):
        with open(error_log_path, 'w') as f:
            json.dump([], f)
    

    with open(error_log_path, 'r+') as f:
        try:
            error_list = json.load(f)
        except json.JSONDecodeError:
            error_list = []
        
        error_list.append(item_index)
        
        f.seek(0)
        json.dump(error_list, f)
        
        f.truncate()

        
def call_agent_with_backoff(item_index, text_summary, baseline, max_retries=5, return_dict=None, delay=30):
    for retry in range(max_retries):
        try:
            risk_scenario_index = item_index.split('_')[0]
            current_memory_path = os.path.join(os.path.dirname(__file__), f"./memory/good_memory_{risk_scenario_index}.json")
            current_config_path = os.path.join(os.path.dirname(__file__), f"./baselines/{baseline}_config.json")
            Agent(item_index, text_summary, baseline,current_memory_path,current_config_path)
            if return_dict is not None:
                return_dict['result'] = True
            return True
        except Exception as e:
            print(f"Error: {e}, retrying {retry + 1}/{max_retries}...")
            time.sleep(delay)
            delay *= 2
    if return_dict is not None:
        return_dict['error'] = f"Max retries reached. Function failed for {item_index}."
    
    print("Max retries reached. Function failed.")
    return False


def call_agent_process(item_index, text_summary, baseline, max_retries, return_dict):

    try:
        result = call_agent_with_backoff(item_index, text_summary, baseline, max_retries)
        return_dict['result'] = result
    except Exception as e:
        return_dict['error'] = str(e)

def call_agent_with_timeout(item_index, text_summary, baseline, gpu_number, timeout, max_retries=5):
    print(f"call_agent_with_timeout, index = {item_index}")

    manager = multiprocessing.Manager()
    return_dict = manager.dict()

    process = multiprocessing.Process(target=call_agent_with_backoff, args=(item_index, text_summary, baseline, max_retries, return_dict))
    
    process.start() 
    
    process.join(timeout) 

    if process.is_alive():

        print(f"Timeout: Item {item_index} exceeded {timeout} seconds.")
        process.terminate()
        process.join()
        log_error_item(item_index)
        
        delete_docker(f"{baseline}_{gpu_number}_container")
        container = create_docker(f"{baseline}_{gpu_number}_container", llm="DS-6.7B", is_OCI=True)

        return False
    else:
        print(f"return_dict = {return_dict}")
        if 'result' in return_dict:
            return return_dict['result']
        elif 'error' in return_dict:
            print(f"Error in process: {return_dict['error']}")
            log_error_item(item_index)
            return False
        else:
            print("Unknown error.")
            log_error_item(item_index)
            return False


def generation(index, data, optimization_func, output_dir_name, prefix):

    for item in data:
        try:
            old_prompt = item['Text_summary']
            print(f"currently processing prompt: {old_prompt}")
            optimized_prompt = optimization_func(old_prompt).get("optimized prompt", "")
            print(f"{prefix} optimized_prompt is: {optimized_prompt}")
            item['Text_summary'] = optimized_prompt
        except Exception as e:
            print(f"Error querying target agent: {e}")
            return ""
    
    output_dir = os.path.join(current_dir,"baselines",output_dir_name)
    os.makedirs(output_dir, exist_ok=True)
    output_file_path = os.path.join(output_dir, f"{prefix}_index{index}_30_codes.json")
    os.makedirs(os.path.dirname(output_file_path), exist_ok=True)
    with open(output_file_path, 'w') as outfile:
        json.dump(data, outfile, indent=4)

    print(f"Updated JSON file has been saved to {output_file_path}")

def evaluation(risk_index, baseline, gpu_number):
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if "Agent" in baseline:
        copy_config(baseline)
        dataset_dir_relative_path = f"baselines/Agent_dataset/Agent_index{risk_index}_30_codes.json"
        baseline_relative_path = "Agent"
    else:
        dataset_dir_relative_path = f"baselines/{baseline}_dataset/{baseline}_index{risk_index}_30_codes.json"
        baseline_relative_path = baseline

    jsonfile = os.path.join(current_dir, dataset_dir_relative_path)

    ### upd config file
    config_file_path = os.path.join(current_dir, "baselines", f"{baseline}_config.json")
    update_config("risk_index", risk_index, config_file_path)
    update_config("risk_scenario", risk_dictionary.get(str(risk_index), "Unknown scenario"), config_file_path)
    update_config("gpu_number", gpu_number, config_file_path)
    update_config("dataset_dir_relative_path", f"{baseline_relative_path}_dataset", config_file_path)
    update_config("conversation_dir_relative_path", f"{baseline_relative_path}_result/conversation_log", config_file_path)
    update_config("evaluation_log_dir_relative_path", f"{baseline_relative_path}_result/evaluation_log", config_file_path)
    update_config("baseline",baseline,config_file_path)

    with open(jsonfile, 'r') as file:
        data = json.load(file)
    
    if("Agent" not in baseline):#not agent, directly run OCI
        for item in data:
            item_index = item['Index']
            OCI(item_index, item['Text_summary'],config_file_path)
    elif("Agent" in baseline):
        initialize_embeddings(file_path=os.path.join(os.path.dirname(__file__), f"./memory/good_memory.json"))
        copy_memory(risk_index)
        for index, item in enumerate(data):#index 
            item_index = item['Index']
            update_config("red_teaming_requirement",item['Text_summary'],file_path = os.path.join(current_dir, "baselines", f"{baseline}_config.json"))
            success = call_agent_with_timeout(item_index, item['Text_summary'], baseline,gpu_number, timeout=1200, max_retries=5)
            print(f"call_agent_with_timeout result:{success}")
            if not success:
                continue

def parse_args():
    global baseline
    parser = argparse.ArgumentParser(description="Choose the range of indexes to process and the baseline method.")
    parser.add_argument('--start_index', type=int, default=1, help="The starting index of the dataset (default is 1).")
    parser.add_argument('--end_index', type=int, default=27, help="The ending index of the dataset (default is 27).")
    parser.add_argument('--baseline', type=str, required=True, 
                        help="The baseline method to use: GCG, AmpleGCG, AutoDAN or Agent.")
    parser.add_argument('--generation', action='store_true', help="Run the generation part of the process.")
    parser.add_argument('--evaluation', action='store_true', help="Run the evaluation part of the process.")

    args = parser.parse_args()
    baseline = args.baseline

    print(f"in main, args baseline = {baseline}")
    return args

def main():

    args = parse_args()
    start_index = args.start_index
    end_index = args.end_index
    global baseline
    baseline = args.baseline

    if args.generation:
        for index in range(start_index, end_index + 1):
            jsonfile_relative_path = f"../../dataset/RedCode-Exec/py2text_dataset_json/index{index}_30_codes_full.json"
            jsonfile = os.path.join(current_dir, jsonfile_relative_path)
            # if(int(index))<=2:
            #     continue
            with open(jsonfile, 'r') as file:
                data = json.load(file)

            if baseline == 'GCG':
                print(f"Processing index {index} with GCG method...")
                generation(index, data, GCG_jailbreak_module, "GCG_dataset", "GCG")
            
            elif baseline == 'AmpleGCG':
                print(f"Processing index {index} with AmpleGCG method...")
                generation(index, data, AmpleGCG_jailbreak_module, "AmpleGCG_dataset", "AmpleGCG")

            elif baseline == 'Advprompter':
                print(f"Processing index {index} with Advprompter method...")
                generation(index, data, Advprompter_jailbreak_module, "Advprompter_dataset", "Advprompter")
            elif baseline == 'AutoDAN':
                print(f"Processing index {index} with AutoDan method...")
                generation(index, data, AutoDAN_jailbreak_module, "AutoDAN_dataset", "AutoDAN")
            else:
                print("alg. not support")
            

    if args.evaluation:
        gpu_number = os.getenv('CUDA_VISIBLE_DEVICES')
        llm = "DS-6.7B"
        config_file_path = os.path.join(os.path.dirname(__file__),f"./baselines/{baseline}_config.json")
        # print(f"config_file_path == {config_file_path}")
        container = create_docker(f"{baseline}_{gpu_number}_container", llm, is_OCI=True) # change this docker name when do paralell exp
        for risk_index in range(start_index, end_index + 1):
            evaluation(risk_index, baseline,gpu_number)
        if container:
            container.stop()
            # container.remove()
            print(f"Docker container {container.name} has been stopped and removed.")

if __name__ == "__main__":
    main()


