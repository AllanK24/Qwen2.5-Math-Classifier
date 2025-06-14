import os
import wandb
import torch
from peft import LoraConfig
from utils.train import train
from huggingface_hub import login
from accelerate import Accelerator
from accelerate.utils import set_seed
from utils.summarize_model import summarize_model
from utils.create_dataloaders import create_dataloaders
from utils.llama32.create_llama32 import create_llama32_classifier
from utils.qwen25.create_qwen25 import create_qwen25_classifier_with_lora

MODEL_ID = "Qwen/Qwen2.5-3B"

def main():
    # Set the seed for reproducibility
    set_seed(42)
    
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch._dynamo.config.suppress_errors = True
    
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    
    # Logins
    from kaggle_secrets import UserSecretsClient
    user_secrets = UserSecretsClient()
    secret_value_0 = user_secrets.get_secret("HF_TOKEN")
    secret_value_1 = user_secrets.get_secret("WANDB")
    
    wandb.login(key=secret_value_1)
    login(token=secret_value_0)

    lora_config = LoraConfig(
        r              = 16,         
        lora_alpha     = 32,         
        lora_dropout   = 0.1,       
        target_modules = [
            "q_proj", "k_proj",
            "v_proj", "o_proj" 
        ],
    
        bias           = "all",     
        inference_mode = False 
    )
    
    # Create the model and tokenizer
    model, tokenizer = create_qwen25_classifier_with_lora(
        model_id=MODEL_ID,
        num_classes=8,
        add_dropout=True,
        dropout_prob=0.5,
        device="cuda",
        lora_config=lora_config
    )
    
    # Print the model summary
    summarize_model(model, tokenizer, prompt="Hello World!")
    
    # Create train and val dataloaders
    train_data_path = "/kaggle/input/math-classifier-competition/train.csv"
    val_data_path = "/kaggle/input/math-classifier-competition/val.csv"
    BATCH_SIZE = 1
    NUM_WORKERS = os.cpu_count()
    
    train_dataloader, val_dataloader = create_dataloaders(
        train_dataset_path=train_data_path,
        val_dataset_path=val_data_path,
        shuffle=True,
        batch_size=BATCH_SIZE,
        num_workers=NUM_WORKERS,
        tokenizer=tokenizer,
    )
    
    # Set up the hyperparameters
    LEARNING_RATES = {
        "base_model": 0.00005,
        "classifier": 0.0001,
    }
    EPOCHS = 5
    WEIGHT_DECAY = 0.001
    LABEL_SMOOTHING = 0.1
    # GRADIENT_ACCUMULATION_STEPS = 1
    
    # Set up the accelerator
    accelerator = Accelerator(
        device_placement=True,
        split_batches=True,
        mixed_precision="fp16",
        # gradient_accumulation_steps=GRADIENT_ACCUMULATION_STEPS,
        cpu=False
    )
    print(f"Using {accelerator.num_processes} GPUs")  # Should print 2
    
    # Set up the loss function
    loss_fn = torch.nn.CrossEntropyLoss(label_smoothing=LABEL_SMOOTHING)
    
    # Set up the optimizer
    optimizer = torch.optim.AdamW(
        [
            {'params': model.qwen_base.parameters(), 'lr': LEARNING_RATES["base_model"]}, 
            {'params': model.classifier.parameters(), 'lr': LEARNING_RATES["classifier"]},
        ],
        weight_decay=WEIGHT_DECAY
    )
    
    # Config
    config = {
        "model_id": MODEL_ID,
        "learning_rate": LEARNING_RATES,
        "epochs": EPOCHS,
        "batch_size": BATCH_SIZE,
        "weight_decay": WEIGHT_DECAY,
        "label_smoothing": LABEL_SMOOTHING,
        "num_workers": NUM_WORKERS,
        "dropout": 0.5,
        "lora": True
    }
    
    if accelerator.is_main_process:
        # Initialize wandb before training
        wandb.init(
            project='qwen25_math_classifier', # Project name
            name='9th', # Run name
            config=config # Train config: lr, epochs and etc
        )
    
    # Train the model
    results = train(
        model=model,
        train_dataloader=train_dataloader,
        val_dataloader=val_dataloader,
        loss_fn=loss_fn,
        optimizer=optimizer,
        epochs=EPOCHS,
        accelerator=accelerator,
        f1_avg_mode="macro",
        checkpoint_every_n_epochs=2,
        save_path="./finetuned_model/"
    )
    
    # Finish wandb run
    wandb.finish()

if __name__=="__main__":
    main()