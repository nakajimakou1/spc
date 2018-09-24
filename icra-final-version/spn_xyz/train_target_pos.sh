#!/bin/bash
python train_torcs.py \
    --save-path mpc_10_cont_nopretrain_target_speed \
    --continuous \
    --one-hot \
    --use-seg \
    --lstm2 \
    --num-total-act 2 \
    --pred-step 10 \
    --buffer-size 50000 \
    --epsilon-frames 100000 \
    --batch-size 32 \
    --use-collision \
    --use-offroad \
    --use-distance \
    --use-pos \
    --sample-with-collision \
    --sample-with-offroad \
    --num-same-step 1 \
    --data-parallel \
    --id 25 \
    --target-pos 3 \
    --sample-with-pos \
    --resume
