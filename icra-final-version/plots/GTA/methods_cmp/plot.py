# -*- coding: utf-8 -*-
from __future__ import division, print_function
import numpy as np
import copy
import matplotlib.pyplot as plt


def smooth(array, m=3):
    _array = copy.deepcopy(array)
    std = np.zeros_like(array)
    n = _array.shape[0]
    for i in range(1, n):
        _array[i] = np.mean(array[max(0, i - m): min(n, i + m + 1)])
        std[i] = np.std(array[max(0, i - m): min(n, i + m + 1)])
    return _array, std


def cut(array, m1=300, m2=200, l=30):
    n = array.shape[0]
    start = max(min(int((n-l)/2), m1), 0)
    end = min(max(int((n+l)/2), n-m2), n)
    return array[start:end].mean()

def read(fname, idx):
    steps = []
    rewards = []
    test = True

    with open(fname, 'r') as f:
        for line in f.readlines():
            entry = line.split(' ')
            if idx == 7:
                test = not test
            if test:
                steps.append(int(entry[1]))
                rewards.append(eval(entry[idx]))
            if int(entry[1]) > 390000:
                break
    steps = np.array(steps) / 100000.0
    rewards = np.array(rewards) / 1000.0
    rewards, std = smooth(rewards, 25)
    std = std / 3
    plt.plot(steps, rewards)
    plt.fill_between(steps, rewards+std, rewards-std, alpha=0.5)
    return steps, rewards, std


def plot_reward():
    plt.style.use('seaborn-darkgrid')
    plt.rcParams['font.family'] = 'serif'
    plt.rcParams['font.serif'] = 'Ubuntu'
    plt.rcParams['font.monospace'] = 'Ubuntu Mono'
    plt.rcParams['font.size'] = 20
    plt.rcParams['axes.labelsize'] = 20
    # plt.rcParams['axes.labelweight'] = 'bold'
    plt.rcParams['axes.titlesize'] = 20
    plt.rcParams['xtick.labelsize'] = 20
    plt.rcParams['ytick.labelsize'] = 20
    plt.rcParams['legend.fontsize'] = 20
    plt.rcParams['figure.titlesize'] = 20

    width, height = plt.figaspect(0.68)
    fig = plt.figure(figsize=(width, height), dpi=300)

    read('spl.txt', 7)
    read('model_based_rl_30w_1.txt', 3)
    read('ddpg_seg_1.txt', 3)
    read('ddpg_rgb.txt', 3)

    plt.xlabel(r'Steps / $10^5$')
    plt.ylabel(r'Reward / $10^3$')
    plt.ylim(0, 8)
    plt.legend(['SPN',
                'GCG',
                'DDPG-Seg',
                'DDPG'])
    plt.tight_layout()
    plt.savefig('../methods_cmp_gta.png', dpi=300)

plot_reward()
