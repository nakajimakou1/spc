#!/bin/bash
python train_torcs.py --save-path mpc_10_gta --env 'gta' --learning-freq 10 --num-train-steps 20 --simple-seg --continuous --one-hot --use-seg --lstm2 --num-total-act 2 --pred-step 8 --buffer-size 50000 --epsilon-frames 100000 --batch-size 20 --use-collision --use-offroad --use-speed --sample-with-collision --sample-with-offroad --num-same-step 1 --data-parallel --id 25 --resume