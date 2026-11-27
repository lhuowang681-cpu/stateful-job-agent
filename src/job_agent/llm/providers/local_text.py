"""Explicit offline text inference with measured tokens and bounded generation.

Separate from the historical LocalStructuredRunner adapter whose API is kept.
"""
from pathlib import Path
from hashlib import sha256
from time import perf_counter
from threading import RLock
from collections import deque
import json
from job_agent.llm.provider import ProviderContractError
from job_agent.llm.providers.mock import result_from_raw_output
from job_agent.llm.providers.transformers import extract_json_object


class OfflineInputBudgetError(ProviderContractError):
    error_code='input_token_budget'


class OfflineBusyError(ProviderContractError):
    error_code='local_model_busy'


class OfflineTextProvider:
    provider_name='offline-transformers'

    def __init__(self,path,*,device='cuda:0',max_input_tokens=8192,max_output_tokens=512,
                 generation_seconds=25,capture_synthetic_outputs=False):
        if not (1<=max_input_tokens<=8192 and 1<=max_output_tokens<=1600 and 0<generation_seconds<=25):
            raise ValueError('offline_text_budget_invalid')
        import torch,transformers
        from transformers import AutoTokenizer,AutoModelForCausalLM,GenerationConfig
        folder=Path(path).resolve()
        if not folder.is_dir():raise ValueError('local_text_model_directory_required')
        paths=sorted({*folder.glob('*.safetensors'),*folder.glob('*.safetensors.index.json'),
            *[folder/n for n in ('config.json','generation_config.json','tokenizer_config.json','tokenizer.json','vocab.json','merges.txt') if (folder/n).is_file()]})
        if not any(p.suffix=='.safetensors' for p in paths):raise ValueError('local_safetensors_required')
        files={}
        for p in paths:
            digest=sha256()
            with p.open('rb') as handle:
                for block in iter(lambda:handle.read(8*1024*1024),b''):digest.update(block)
            files[p.name]=digest.hexdigest()
        revision=sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
        config={'max_input_tokens':max_input_tokens,'max_output_tokens':max_output_tokens,
            'generation_seconds':generation_seconds,'torch':torch.__version__,'transformers':transformers.__version__,
            'dtype':'bfloat16' if device.startswith('cuda') else 'float32','attention':'sdpa'}
        policy_hash=sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
        self.model=f'{folder.name}@{revision}:{policy_hash[:16]}'
        self.identity={'provider':self.provider_name,'model_name':folder.name,'revision':revision,'policy':config,'file_hashes':files}
        self.tokenizer=AutoTokenizer.from_pretrained(str(folder),local_files_only=True,trust_remote_code=False)
        self.network=AutoModelForCausalLM.from_pretrained(str(folder),local_files_only=True,trust_remote_code=False,
            use_safetensors=True,dtype=torch.bfloat16 if device.startswith('cuda') else torch.float32,
            attn_implementation='sdpa').to(device).eval()
        self.identity.update(architecture=type(self.network).__name__,parameter_count=sum(p.numel() for p in self.network.parameters()),
            loaded_device=str(next(self.network.parameters()).device),loaded_dtype=str(next(self.network.parameters()).dtype))
        self.generation_config=GenerationConfig.from_model_config(self.network.config)
        self.generation_config.eos_token_id=self.network.generation_config.eos_token_id or self.tokenizer.eos_token_id
        self.generation_config.pad_token_id=self.tokenizer.pad_token_id if self.tokenizer.pad_token_id is not None else self.tokenizer.eos_token_id
        self.device=device;self.max_input_tokens=max_input_tokens;self.max_output_tokens=max_output_tokens
        self.generation_seconds=generation_seconds;self.seed=0;self.calls=deque(maxlen=1024);self._lock=RLock()
        self.capture_synthetic_outputs=capture_synthetic_outputs

    def generate_structured(self,*,system_prompt,user_prompt,output_schema,tools,temperature,max_output_tokens,trace):
        import torch
        if tools:raise ProviderContractError('offline_text_tools_not_supported')
        if not self._lock.acquire(timeout=2):
            self.calls.append({'dispatched':False,'error_code':'local_model_busy'})
            raise OfflineBusyError('offline_text_busy')
        row=None
        try:
            started=perf_counter()
            messages=[{'role':'system','content':system_prompt},{'role':'user','content':user_prompt}]
            inputs=self.tokenizer.apply_chat_template(messages,add_generation_prompt=True,tokenize=True,return_tensors='pt',return_dict=True)
            count=inputs['input_ids'].shape[1]
            if count>self.max_input_tokens:
                self.calls.append({'dispatched':False,'input_tokens':count,'error_code':'input_token_budget'})
                raise OfflineInputBudgetError('offline_text_input_token_budget')
            cap=min(max_output_tokens,self.max_output_tokens)
            row={'dispatched':False,'node_id':trace.node_id,'run_id':trace.run_id,'input_tokens':count,
                'output_tokens':None,'status':'preparing','cap':cap,'seed':self.seed,'temperature':temperature,
                'prompt_hash':sha256((system_prompt+'\n'+user_prompt).encode()).hexdigest()}
            self.calls.append(row)
            inputs={k:v.to(self.device) for k,v in inputs.items()}
            rng_devices=[torch.device(self.device).index or 0] if self.device.startswith('cuda') else []
            with torch.random.fork_rng(devices=rng_devices),torch.inference_mode():
                torch.manual_seed(self.seed)
                row['dispatched']=True;row['status']='started'
                generated=self.network.generate(**inputs,generation_config=self.generation_config,
                    max_new_tokens=cap,max_time=self.generation_seconds,do_sample=temperature>0,
                    **({'temperature':temperature} if temperature>0 else {}))
            ids=generated[0,count:].tolist();raw=self.tokenizer.decode(ids,skip_special_tokens=True)
            eos=self.generation_config.eos_token_id
            eos={eos} if isinstance(eos,int) else set(eos)
            stopped=bool(ids) and ids[-1] in eos
            truncated=not stopped
            latency=int((perf_counter()-started)*1000)
            row.update({'output_tokens':len(ids),'status':'completed','latency_ms':latency,
                'finish_reason':'stop' if stopped else 'length' if len(ids)>=cap else 'time_limit',
                'output_hash':sha256(raw.encode()).hexdigest()})
            if self.capture_synthetic_outputs:row['synthetic_raw_output']=raw
            result=result_from_raw_output(provider=self.provider_name,model=self.model,raw_output=raw,
                output_schema=output_schema,parse_output=extract_json_object(raw),trace=trace,latency_ms=latency,
                input_tokens=count,output_tokens=len(ids))
            return result.model_copy(update={'finish_reason':row['finish_reason'],'completion_truncated':truncated,
                **({'schema_valid':False,'parsed_output':None,'error_code':'completion_truncated'} if truncated else {})})
        except BaseException:
            if row is not None and row['status']!='completed':row['status']='failed';row['error_code']='local_inference_failed'
            raise
        finally:self._lock.release()
