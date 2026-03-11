import json
import os

def read_config(file_path):

    if not os.path.exists(file_path):
        return {} 

    with open(file_path, 'r') as f:
        config = json.load(f)
        
    return config

def write_config(config, file_path = os.path.join(os.path.dirname(__file__), '../baselines/Agent_config.json')):

    with open(file_path, 'w') as f:
        json.dump(config, f, indent=4)
        f.flush()  
        os.fsync(f.fileno())  

def update_config(key, value, file_path):

    config = read_config(file_path)
    config[key] = value  
    write_config(config, file_path)
    print(f"Key '{key}' updated with value: {value}")

def get_config_value(key, file_path):
    config = read_config(file_path)
    return str(config.get(key, None))
