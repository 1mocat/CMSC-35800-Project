from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel, PeftConfig
import os
import time


def advprompter_generate(old_prompt):
    current_path = os.path.dirname(os.path.abspath(__file__))

    model_path = os.path.join(current_path, "advprompter_checkpoint")
    print(f"model_path = {model_path}")

    base_model_name = "meta-llama/Llama-2-7b-hf"

    base_model = AutoModelForCausalLM.from_pretrained(base_model_name)
    tokenizer = AutoTokenizer.from_pretrained(base_model_name)
    adapter_config = PeftConfig.from_pretrained(model_path)
    model = PeftModel.from_pretrained(base_model, model_path)

    start_time = time.time()
    input_ids = tokenizer(old_prompt, return_tensors="pt").input_ids

    outputs = model.generate(input_ids, max_new_tokens=50)
    response = tokenizer.decode(outputs[0], skip_special_tokens=True)

    end_time = time.time()
    execution_time = end_time - start_time

    print("advprompter_generate: ", response)
    print(f"### advprompter_generate time cost: {execution_time:.2f} seconds")

    return response

