from __future__ import division, print_function
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import optim
from torch.autograd import Variable
import numpy as np
import pickle as pkl
from torch.utils.data import Dataset, DataLoader
import os
import time
import math
import PIL.Image as Image
import random
from sklearn.metrics import confusion_matrix
import pdb
from scipy.misc import imsave
import copy
import matplotlib.pyplot as plt
from sklearn.preprocessing import OneHotEncoder


def get_from_dict(info, key):
    return info[key] if key in info.keys() else None


def weights_init(m):
    classname = m.__class__.__name__
    if classname.find('Conv') != -1:
        weight_shape = list(m.weight.data.size())
        fan_in = np.prod(weight_shape[1: 4])
        fan_out = np.prod(weight_shape[2: 4]) * weight_shape[0]
        w_bound = np.sqrt(6. / (fan_in + fan_out))
        m.weight.data.uniform_(-w_bound, w_bound)
        m.bias.data.fill_(0)
    elif classname.find('Linear') != -1:
        weight_shape = list(m.weight.data.size())
        fan_in = weight_shape[1]
        fan_out = weight_shape[0]
        w_bound = np.sqrt(6. / (fan_in + fan_out))
        m.weight.data.uniform_(-w_bound, w_bound)
        m.bias.data.fill_(0)
    elif classname.find('BatchNorm') != -1:
        m.weight.data.fill_(1)
        m.bias.data.fill_(0)


def train_model_new(args, train_net, mpc_buffer, tt):
    optimizer = optim.Adam(train_net.module.conv_lstm.drnseg.parameters(), lr=args.lr, amsgrad=True)
    for i in range(args.num_train_steps):
        obs, target = mpc_buffer.sample_seg(args.batch_size)
        seg = train_net(obs, function='predict_seg')
        optimizer.zero_grad()
        loss = nn.NLLLoss()(seg, target)
        loss.backward()
        optimizer.step()
        with open(os.path.join(args.save_path, 'seg_ls.txt'), 'a') as f:
            f.write('seg step %d loss %0.4f\n' % (tt, loss.data.cpu().numpy()))
        print(('step %d loss %0.4f' % (i, loss.data.cpu().numpy())))

    optimizer = optim.Adam(train_net.module.conv_lstm.coll_layer.parameters(), lr=args.lr, amsgrad=True)
    for i in range(args.num_train_steps):
        feature, target = mpc_buffer.sample_collision(args.batch_size)
        collision = train_net(feature, function='predict_collision')
        optimizer.zero_grad()
        loss = nn.CrossEntropyLoss()(collision, target)
        loss.backward()
        optimizer.step()
        tn, fp, fn, tp = confusion_matrix(target, torch.max(collision, -1)[1], labels = [0, 1]).ravel()
        accuracy = (tn + tp) / (tn + fp + fn + tp) * 100.0
        # pdb.set_trace()
        with open(os.path.join(args.save_path, 'coll_acc.txt'), 'a') as f:
            f.write('step %d accuracy %0.4f loss %0.4f\n' % (tt, accuracy, loss.data.cpu().numpy()))
        print(('collision accuracy %0.2f loss %0.4f' % (accuracy, loss.data.cpu().numpy())))

    optimizer = optim.Adam(train_net.module.conv_lstm.off_layer.parameters(), lr=args.lr, amsgrad=True)
    for i in range(args.num_train_steps):
        feature, target = mpc_buffer.sample_offroad(args.batch_size)
        offroad = train_net(feature, function='predict_offroad')
        optimizer.zero_grad()
        loss = nn.CrossEntropyLoss()(offroad, target)
        loss.backward()
        optimizer.step()
        tn, fp, fn, tp = confusion_matrix(target, torch.max(offroad, -1)[1], labels = [0, 1]).ravel()
        accuracy = (tn + tp) / (tn + fp + fn + tp) * 100.0
        # pdb.set_trace()
        with open(os.path.join(args.save_path, 'off_acc.txt'), 'a') as f:
            f.write('step %d accuracy %0.4f loss %0.4f\n' % (tt, accuracy, loss.data.cpu().numpy()))
        print(('offroad accuracy %0.2f loss %0.4f' % (accuracy, loss.data.cpu().numpy())))

    optimizer = optim.Adam(train_net.module.conv_lstm.dist_layer.parameters(), lr=args.lr, amsgrad=True)
    for i in range(args.num_train_steps):
        feature, target = mpc_buffer.sample_distance(args.batch_size)
        distance = train_net(feature, function='predict_distance')
        optimizer.zero_grad()
        loss = nn.MSELoss()(distance, target)
        loss.backward()
        optimizer.step()
        with open(os.path.join(args.save_path, 'pred_ls.txt'), 'a') as f:
            f.write('step %d loss %0.4f\n' % (tt, loss.data.cpu().numpy()))
        print(('distance step %d loss %0.4f' % (i, loss.data.cpu().numpy())))

    if args.use_lstm:
        coll_acc = 0
        off_acc = 0
        optimizer = optim.Adam([param for param in train_net.module.conv_lstm.encode_action.parameters()] + [param for param in train_net.module.conv_lstm.feature_map_predictor.parameters()] + [param for param in train_net.module.conv_lstm.action_up1.parameters()] + [param for param in train_net.module.conv_lstm.action_up2.parameters()], lr=args.lr, amsgrad=True)
        for i in range(args.num_train_steps):
            feature, action, target, signals = mpc_buffer.sample_seq()
            seg = train_net(feature, action, function='predict_feature')
            optimizer.zero_grad()
            loss = nn.NLLLoss()(seg, target)
            loss.backward()
            optimizer.step()

            seg = seg.detach()
            with torch.no_grad():
                collision = torch.argmax(train_net.predict_collision(seg), -1).cpu()
                offroad = torch.argmax(train_net.predict_offroad(seg), -1).cpu()
            coll_acc += collision == signals['collision']
            off_acc += offroad == signals['offroad']

            with open(os.path.join(args.save_path, 'pred_ls.txt'), 'a') as f:
                f.write('step %d loss %0.4f\n' % (tt, loss.data.cpu().numpy()))
            print(('seq step %d loss %0.4f' % (i, loss.data.cpu().numpy())))
        with open(os.path.join(args.save_path, 'signal_acc.txt'), 'a') as f:
            f.write('train step %d\n' % tt)
            for i in range(20):
                f.write('step %d coll_acc %0.2f off_acc %0.2f\n' % (i+1, float(coll_acc[i])*100/args.num_train_steps, float(off_acc[i])*100/args.num_train_steps))
    else:
        optimizer = optim.Adam([param for param in train_net.module.conv_lstm.actionEncoder.parameters()] + [param for param in train_net.module.conv_lstm.feature_map_predictor.parameters()], lr=args.lr, amsgrad=True)
        for i in range(args.num_train_steps):
            feature, action, target = mpc_buffer.sample_fcn(args.batch_size)
            _, seg = train_net(feature, action, function='predict_fcn')
            optimizer.zero_grad()
            if args.one_hot:
                loss = nn.NLLLoss()(seg, target)
            else:
                loss = nn.MSELoss()(seg, target)
            loss.backward()
            optimizer.step()
            with open(os.path.join(args.save_path, 'pred_ls.txt'), 'a') as f:
                f.write('step %d loss %0.4f\n' % (tt, loss.data.cpu().numpy()))
            print(('fcn step %d loss %0.4f' % (i, loss.data.cpu().numpy())))
    visualize2(torch.argmax(seg, 1).cpu().numpy(), target.cpu().numpy())


def visualize2(seg, gt):
    if not os.path.isdir('visualize'):
        os.mkdir('visualize')
    for i in range(seg.shape[0]):
        imsave(os.path.join('visualize', 'step%d.png' % (i+1)), np.concatenate([draw_from_pred(seg[i]), draw_from_pred(gt[i])], 1))


def train_model(args, train_net, mpc_buffer, epoch, avg_img_t, std_img_t):
    if epoch % 20 == 0:
        target, idxes = mpc_buffer.sample(args.batch_size, sample_early=True)
    else:
        target, idxes = mpc_buffer.sample(args.batch_size, sample_early=False)

    for key in target.keys():
        target[key] = Variable(torch.from_numpy(target[key]).float(), requires_grad=False)

    if args.use_seg:
        target['seg_batch'] = target['seg_batch'].long()
    else:
        with torch.no_grad():
            nximg_enc = train_net(target['nx_obs_batch'], get_feature=True).detach()

    if args.normalize:
        target['obs_batch'] = (target['obs_batch'] - avg_img_t) / std_img_t
        target['nx_obs_batch'] = (target['nx_obs_batch'] - avg_img_t) / std_img_t
    else:
        target['obs_batch'] = target['obs_batch'] / 255.0
        target['nx_obs_batch'] = target['nx_obs_batch'] / 255.0

    if torch.cuda.is_available():
        for key in target.keys():
            target[key] = target[key].to(torch.device("cuda:0"))

    output = train_net(target['obs_batch'], target['act_batch'], action_var=target['prev_action'])

    loss = 0

    weight = (0.97 ** np.arange(args.pred_step)).reshape((1, args.pred_step, 1))
    weight = Variable(torch.from_numpy(weight).float().cuda(), requires_grad=False).repeat(args.batch_size, 1, 1)

    if args.use_collision:
        show_accuracy(target['coll_batch'].view(-1), torch.max(output['coll_prob'].view(-1, 2), -1)[1], 'collision')
        coll_ls = nn.CrossEntropyLoss()(output['coll_prob'].view(-1, 2), target['coll_batch'].view(-1).long())
        loss += coll_ls
        print('coll ls', coll_ls.data.cpu().numpy())

    if args.use_offroad:
        if 'torcs' in args.env:
            show_accuracy(target['off_batch'].view(-1), torch.max(output['offroad_prob'].view(-1, 2), -1)[1], 'offroad')
            offroad_ls = nn.CrossEntropyLoss()(output['offroad_prob'].view(-1, 2), target['off_batch'].view(-1).long())
        elif 'carla' in args.env:
            offroad_ls = nn.BCELoss()(F.sigmoid(output['offroad_prob'].view(-1)), target['off_batch'].view(-1))
        loss += offroad_ls
        print('offroad ls', offroad_ls.data.cpu().numpy())

    if args.use_otherlane:
        otherlane_ls = nn.BCELoss()(output['otherlane'].view(-1), target['otherlane_batch'].view(-1))
        loss += otherlane_ls
        print('offroad ls', offroad_ls.data.cpu().numpy())

    if args.use_distance:
        dist_ls = torch.sqrt(nn.MSELoss()(output['dist'].view(-1, args.pred_step), target['dist_batch'][:, 1:].view(-1, args.pred_step))) 
        loss += 0.01 * dist_ls
        print('dist ls', dist_ls.data.cpu().numpy())

    if args.use_seg:
        output['seg_pred'] = output['seg_pred'].view(args.batch_size * (args.pred_step + 1), args.classes, 256, 256)
        target['seg_batch'] = target['seg_batch'].view(args.batch_size * (args.pred_step + 1), 256, 256)
        pred_ls = nn.NLLLoss()(output['seg_pred'], target['seg_batch'])
    else:
        pred_ls = torch.sqrt(nn.MSELoss()(output['seg_pred'], nximg_enc))
    print('pred ls', pred_ls.data.cpu().numpy()) # nan here!
    loss += pred_ls

    if args.use_pos:
        pos_loss = torch.sqrt((nn.MSELoss()(torch.exp(output['pos']/10), torch.exp(target['pos_batch'][:, :, :]/10))))
        loss += pos_loss
        print('pos ls', pos_loss.data.cpu().numpy())
    if args.use_angle:
        angle_loss = torch.sqrt((nn.MSELoss()(torch.exp(output['angle']), torch.exp(target['angle_batch'][:, 1:, :]))))
        loss += angle_loss
        print('angle ls', angle_loss.data.cpu().numpy())
    if args.use_speed:
        speed_loss = torch.sqrt(nn.MSELoss()(output['speed'], target['sp_batch'][:, 1:, :]))
        loss += speed_loss
        print('speed ls', speed_loss.data.cpu().numpy())
    if args.use_xyz:
        xyz_loss = torch.sqrt(nn.MSELoss()(output['xyz'], target['xyz_batch'][:, 1:, :])) / 100.0
        loss += xyz_loss
        print('xyz ls', xyz_loss.data.cpu().numpy())

    loss_value = float(loss.data.cpu().numpy())
    if np.isnan(loss_value):
        pdb.set_trace()
    visualize(args, target, output)
    return loss


def draw_from_pred_torcs(pred):
    illustration = np.zeros((256, 256, 3)).astype(np.uint8)
    illustration[:, :, 0] = 255
    illustration[pred == 1] = np.array([0, 255, 0])
    illustration[pred == 2] = np.array([0, 0, 0])
    illustration[pred == 3] = np.array([0, 0, 255])
    return illustration


def draw_from_pred_carla(array):
    classes = {
        0: [0, 0, 0],         # None
        1: [70, 70, 70],      # Buildings
        2: [190, 153, 153],   # Fences
        3: [72, 0, 90],       # Other
        4: [220, 20, 60],     # Pedestrians
        5: [153, 153, 153],   # Poles
        6: [157, 234, 50],    # RoadLines
        7: [128, 64, 128],    # Roads
        8: [244, 35, 232],    # Sidewalks
        9: [107, 142, 35],    # Vegetation
        10: [0, 0, 255],      # Vehicles
        11: [102, 102, 156],  # Walls
        12: [220, 220, 0]     # TrafficSigns
    }

    result = np.zeros((array.shape[0], array.shape[1], 3))
    for key, value in classes.items():
        result[np.where(array == key)] = value
    return result


def draw_from_pred_carla_simple(array):
    classes = {
        0: [0, 0, 255],         # None
        1: [255, 0, 0],      # Buildings
        2: [255, 0, 255],   # Fences
        3: [0, 0, 0],       # Other
    }

    result = np.zeros((array.shape[0], array.shape[1], 3))
    for key, value in classes.items():
        result[np.where(array == key)] = value
    return result


def visualize(args, target, output):
    if not os.path.isdir('visualize'):
        os.mkdir('visualize')
    batch_id = np.random.randint(args.batch_size)
    if 'torcs' in args.env:
        draw_from_pred = draw_from_pred_torcs
    elif 'carla' in args.env:
        draw_from_pred = draw_from_pred_carla_simple if args.simple_seg else draw_from_pred_carla

    if args.use_seg:
        # observation = (from_variable_to_numpy(target['obs_batch'][batch_id, :, -3:, :, :]) * 56.1524832523 + 112.62289744791671).astype(np.uint8).transpose(0, 2, 3, 1)
        observation = (from_variable_to_numpy(target['obs_batch'][batch_id, :, -3:, :, :]) * 255.0).astype(np.uint8).transpose(0, 2, 3, 1)
        target['seg_batch'] = target['seg_batch'].view(args.batch_size, args.pred_step + 1, 256, 256)
        segmentation = from_variable_to_numpy(target['seg_batch'][batch_id])
        output['seg_pred'] = output['seg_pred'].view(args.batch_size, args.pred_step + 1, args.classes, 256, 256)
        _, prediction = torch.max(output['seg_pred'][batch_id], 1)
        prediction = from_variable_to_numpy(prediction)
        for i in range(args.pred_step):
            imsave('visualize/%d.png' % i, np.concatenate([observation[i], draw_from_pred(segmentation[i]), draw_from_pred(prediction[i])], 1))
    
    with open(args.save_path+'/report.txt', 'a') as f:
        f.write('target collision:\n')
        f.write(str(from_variable_to_numpy(target['coll_batch'][batch_id])) + '\n')
        f.write('output collision:\n')
        f.write(str(from_variable_to_numpy(output['coll_prob'][batch_id])) + '\n')

        f.write('target offroad:\n')
        f.write(str(from_variable_to_numpy(target['off_batch'][batch_id])) + '\n')
        f.write('output offroad:\n')
        f.write(str(from_variable_to_numpy(output['offroad_prob'][batch_id])) + '\n')

        if args.use_pos:
            f.write('target pos:\n')
            f.write(str(from_variable_to_numpy(target['pos_batch'][batch_id, :-1])) + '\n')
            f.write('output pos:\n')
            f.write(str(from_variable_to_numpy(output['pos'][batch_id])) + '\n')

        if args.use_angle:
            f.write('target angle:\n')
            f.write(str(from_variable_to_numpy(target['angle_batch'][batch_id, :-1])) + '\n')
            f.write('output angle:\n')
            f.write(str(from_variable_to_numpy(output['angle'][batch_id])) + '\n')

        if args.use_speed:
            f.write('target speed:\n')
            f.write(str(from_variable_to_numpy(target['sp_batch'][batch_id, :-1])) + '\n')
            f.write('output speed:\n')
            f.write(str(from_variable_to_numpy(output['speed'][batch_id])) + '\n')

        if args.use_distance:
            f.write('target dist:\n')
            f.write(str(from_variable_to_numpy(target['dist_batch'][batch_id, 1:]))+'\n')
            f.write('output dist:\n')
            f.write(str(from_variable_to_numpy(output['dist'][batch_id, :]))+'\n')


class DoneCondition:
    def __init__(self, size):
        self.size = size
        self.off_cnt = 0
        self.pos = []

    def isdone(self, pos, dist, posxyz, angle):
        if pos <= -6.2 and dist < 0:
            self.off_cnt += 1
        elif pos > -6.2 or dist > 0:
            self.off_cnt = 0
        if self.off_cnt > self.size:
            self.off_cnt = 0
            self.pos = []
            return True
        if abs(pos) >= 21.0:
            self.off_cnt = 0
            self.pos = []
            return True
        self.pos.append(list(posxyz))
        real_pos = np.concatenate(self.pos[-100:])
        real_pos = real_pos.reshape(-1,3)
        std = np.sum(np.std(real_pos, 0))
        if std < 2.0 and len(self.pos) > 100:
            self.pos = []
            self.off_cnt = 0
            return True
        return False


class ObsBuffer:
    def __init__(self, frame_history_len=3):
        self.frame_history_len = frame_history_len
        self.last_obs_all = []

    def store_frame(self, frame):
        obs_np = frame.transpose(2, 0, 1)
        if len(self.last_obs_all) < self.frame_history_len:
            self.last_obs_all = []
            for ii in range(self.frame_history_len):
                self.last_obs_all.append(obs_np)
        else:
            self.last_obs_all = self.last_obs_all[1:] + [obs_np]
        return np.concatenate(self.last_obs_all, 0)

    def clear(self):
        self.last_obs_all = []
        return


class ActionBuffer:
    def __init__(self, frame_history_len=3):
        self.frame_history_len = frame_history_len
        self.last_action_all = []

    def store_frame(self, action):
        if len(self.last_action_all) < self.frame_history_len:
            self.last_action_all = []
            for ii in range(self.frame_history_len):
                self.last_action_all.append(action)
        else:
            self.last_action_all = self.last_action_all[1:] + [action]
        return np.concatenate(self.last_action_all, 0)[np.newaxis,]

    def clear(self):
        self.last_action_all = []
        return


def init_dirs(dir_list):
    for path in dir_list:
        make_dir(path)


def make_dir(path):
    if not os.path.isdir(path):
        os.mkdir(path)


def load_model(path, net, data_parallel=True, optimizer=None, resume=True):
    if resume:
        file_list = sorted(os.listdir(path+'/model'))
        if len(file_list) == 0:
            print('no model to resume!')
            epoch = 0
        else:
            model_path = file_list[-1]
            epoch = pkl.load(open(path+'/epoch.pkl', 'rb'))
            state_dict = torch.load(os.path.join(path, 'model', model_path))
            net.load_state_dict(state_dict)
            print('load success')
    else:
        epoch = 0

    # if optimizer is not None and epoch > 0:
    #     optimizer.load_state_dict(torch.load(os.path.join(path, 'optimizer', 'optimizer.pt')))

    # if optimizer is None:
    return net, epoch
    # else:
    #     return net, epoch, optimizer


def get_info_np(info, use_pos_class = False):
    speed_np = np.array([[info['speed'], info['angle']]])
    if use_pos_class:
        pos = int(round(np.clip(info['trackPos'], -9, 9)) + 9)
        pos_np = np.zeros((1, 19))
        pos_np[0, pos] = 1
    else:
        pos_np = np.array([[info['trackPos']]])
    posxyz_np = np.array([list(info['pos'])])
    return speed_np, pos_np, posxyz_np


def get_info_ls(info):
    speed = [info['speed'], info['angle']]
    pos = [info['trackPos']] + list(info['pos'])
    return speed, pos


def Focal_Loss(probs, target, reduce=True):
    # probs : batch * num_class
    # target : batch,
    loss = -1.0 * (1-probs).pow(3) * torch.log(probs)
    batch_size = int(probs.size()[0])
    loss = loss[torch.arange(batch_size).long().cuda(), target.long()]
    if reduce:
        loss = loss.sum() / (batch_size * 1.0)
    return loss


def sample_cont_action(args, net, imgs, info=None, prev_action=None, testing=False, avg_img=0, std_img=1.0, tt=0, action_var=None):
    imgs = copy.deepcopy(imgs)
    if args.normalize:
        imgs = (imgs.contiguous() - avg_img) / (std_img)
    else:
        imgs = imgs / 255.0
    batch_size, c, w, h = int(imgs.size()[0]), int(imgs.size()[-3]), int(imgs.size()[-2]), int(imgs.size()[-1])
    imgs = imgs.view(batch_size, 1, c, w, h)
    prev_action = prev_action.reshape((1, 1, 2))
    prev_action = np.repeat(prev_action, args.pred_step, axis=1)
    this_action = torch.from_numpy(prev_action).float()
    this_action = Variable(this_action, requires_grad=True)
    this_action.data.clamp(-1, 1)
    prev_loss = 1000
    sign = True
    cnt = 0

    if args.sample_based_planning:
        imgs = imgs.repeat(100, 1, 1, 1, 1)
        action_var = action_var.repeat(100, 1, 1)
        # this_action = torch.stack([torch.ones(100) * 0.5, torch.arange(100) / 50 - 1], dim=1).view(100, 1, 2).repeat(1, args.pred_step, 1)
        # this_action = Variable(this_action.cuda(), requires_grad=False)
        this_action0 = np.arange(10) / 5.0 - 1.0
        this_action1 = np.arange(10) / 10.0 - 0.5
        this_action0 = np.meshgrid(this_action0, this_action1)
        this_action0[0] = this_action0[0].reshape(-1, 1)
        this_action0[1] = this_action0[1].reshape(-1, 1)
        this_action0 = np.concatenate(this_action0, axis=-1)
        this_action = torch.from_numpy(this_action0).view(100, 1, 2).repeat(1, args.pred_step, 1)
        this_action = Variable(this_action.cuda().float(), requires_grad=False)
        loss = np.zeros(100)
        with torch.no_grad():
            start_time = time.time()
            loss = get_action_loss(args, net, imgs, this_action, action_var, None, None, None).data.cpu().numpy()
            # for i in range(4):
            #     loss[100*i: 100*(i+1)] = get_action_loss(args, net, imgs, this_action[100*i: 100*(i+1)], None, None, None).data.cpu().numpy()
            # for i in range(2):
            #     loss[200*i: 200*(i+1)] = get_action_loss(args, net, imgs, this_action[200*i: 200*(i+1)], None, None, None).data.cpu().numpy()
            print('Sampling takes %0.2f seconds.' % (time.time() - start_time))

        if False:
            plt.figure()
            plt.title('pos [%0.2f, %0.2f], trackPos %0.2f, angle %0.2f' % (info['pos'][0], info['pos'][1], info['trackPos'], info['angle']))
            loss2 = loss.reshape((20, 20))
            plt.imshow(loss2)
            plt.colorbar()
            plt.xlabel('acceleration')
            plt.ylabel('steering angle')
            # plt.plot(np.arange(100) / 50.0 - 1, loss)
            plt.tight_layout()
            if not os.path.isdir(os.path.join(args.save_path, 'actions')):
                os.mkdir(os.path.join(args.save_path, 'actions'))
            plt.savefig(os.path.join(args.save_path, 'actions/step_%04d.png' % (tt % 10000)), dpi=100)
            plt.close()
        idx = np.argmin(loss)
        res = this_action0.reshape((100, 2))[idx, :]
        # return np.array([0.5, idx / 50 - 1])
        return res

    else:
        optimizer = optim.Adam([this_action], lr=0.01)
        while sign:
            if testing:
                loss = get_action_loss_test(args, net, imgs, this_action, None, None, None)
            else:
                loss = get_action_loss(args, net, imgs, this_action, None, None, None)
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            this_loss = float(loss.data.cpu().numpy())
            if cnt >= 20 and (np.abs(prev_loss-this_loss)/prev_loss <= 0.0005 or this_loss > prev_loss):
                sign = False
                return this_action.data.cpu().numpy()[0, 0, :].reshape(-1)
            if cnt >= 25:
                sign = False
            cnt += 1
            this_action.data.clamp(-1, 1)  # = torch.clamp(this_action, -1, 1)
            prev_loss = this_loss
        return this_action.data.cpu().numpy()[0, 0, :].reshape(-1)


def from_variable_to_numpy(x):
    x = x.data
    if torch.cuda.is_available():
        x = x.cpu()
    x = x.numpy()
    return x


def generate_action_sample(args, prob, batch_size, length, LAST_ACTION=1):
    all_actions = torch.zeros(batch_size, length).type(torch.LongTensor)
    all_actions[:, 0] = prob[LAST_ACTION].multinomial(num_samples=batch_size, replacement=True).data

    for step in range(1, length):
        indices = [torch.nonzero(all_actions[:, step - 1] == x).squeeze() for x in range(args.num_total_act)]
        for action in range(args.num_total_act):
            if indices[action].numel() > 0:
                all_actions[indices[action], step] = prob[action].multinomial(num_samples = indices[action].numel(), replacement=True).data

    return all_actions


def generate_one_hot_actions(actions, num_actions):
    batch_size, length = actions.size()
    result = torch.zeros(batch_size * length, num_actions)
    actions = actions.view(batch_size * length)
    result[torch.arange(batch_size * length).type(torch.LongTensor), actions] = 1
    result = result.view(batch_size, length, num_actions)
    return result


def generate_probs(args, all_actions, last_action=1):
    all_actions = from_variable_to_numpy(all_actions)
    prob_map = np.concatenate((np.expand_dims(last_action * args.num_total_act + all_actions[:, 0], axis = 1), all_actions[:, :-1] * args.num_total_act + all_actions[:, 1:]), axis = 1)
    prob = torch.histc(torch.from_numpy(prob_map).type(torch.Tensor), bins=args.num_total_act * args.num_total_act).view(args.num_total_act, args.num_total_act)

    prob[prob.sum(dim=1) == 0, :] = 1
    prob /= prob.sum(dim=1).unsqueeze(1)

    return prob


def sample_discrete_action(args, net, obs_var, prev_action=None):
    start_time = time.time()
    obs = np.repeat(np.expand_dims(obs_var, axis=0), args.batch_size, axis=0)
    obs = Variable(torch.from_numpy(obs), requires_grad=False).type(torch.Tensor)
    if torch.cuda.is_available():
        obs = obs.cuda()
    prob = torch.ones(args.num_total_act, args.num_total_act) / float(args.num_total_act)
    with torch.no_grad():
        for i in range(6):
            all_actions = generate_action_sample(args, prob, 6 * args.batch_size, args.pred_step, prev_action)
            one_hot_actions = generate_one_hot_actions(all_actions, args.num_total_act)
            if torch.cuda.is_available():
                one_hot_actions = one_hot_actions.cuda()

            actions = Variable(one_hot_actions, requires_grad=False)
            loss = get_action_loss(args, net, obs, actions)  # needs updating
            all_losses = from_variable_to_numpy(loss)

            if i < 5:
                indices = np.argsort(all_losses)[:args.batch_size]
                prob = generate_probs(args, all_actions[indices], prev_action)
            else:
                idx = np.argmin(all_losses)
                which_action = int(from_variable_to_numpy(all_actions)[idx, 0])

    print('Sampling takes %0.2f seconds, selected action: %d.' % (time.time() - start_time, which_action))
    return which_action


def tile(action, num_total_act):
    return action.view(action.size(0), num_total_act, 1, 1).repeat(1, 1, 64, 64)


def tile_first(x, a, frame_history_len, classes, num_total_act):
    result = [x[:, :classes, :, :]]
    for i in range(frame_history_len - 1):
        result.append(tile(a[:, i, :].float(), num_total_act))
        result.append(x[:, (i+1)*classes:(i+2)*classes, :, :])
    return torch.cat(result, dim=1)


def get_action_loss(args, net, imgs, actions, action_var=None, target=None, hidden=None, cell=None, gpu=0):
    batch_size = int(imgs.size()[0])
    if args.continuous and not args.sample_based_planning:
        batch_size = 1
    if target is None:
        target = dict()
        # if args.sample_with_collision:
        #     target['coll_batch'] = Variable(torch.zeros(batch_size * args.pred_step), requires_grad = False).type(torch.LongTensor)
        # if args.sample_with_offroad:
        #     target['off_batch'] = Variable(torch.zeros(batch_size * args.pred_step), requires_grad = False).type(torch.LongTensor)
        if args.sample_with_pos:
            target['pos_batch'] = Variable(torch.ones(batch_size, args.pred_step, 1) * args.target_pos, requires_grad = False)
        if args.sample_with_angle:
            target['angle_batch'] = Variable(torch.zeros(batch_size, args.pred_step, 1), requires_grad = False)
        if args.target_speed > 0:
            target['speed_batch'] = Variable(torch.ones(batch_size, args.pred_step, 1) * args.target_speed, requires_grad = False)
        if args.target_dist > 0:
            target['dist_batch'] = Variable(torch.ones(batch_size, args.pred_step, 1) * args.target_dist, requires_grad = False)

        if torch.cuda.is_available():
            # if args.sample_with_collision:
            #     target['coll_batch'] = target['coll_batch'].cuda()
            # if args.sample_with_offroad:
            #     target['off_batch'] = target['off_batch'].cuda()
            if args.sample_with_pos:
                target['pos_batch'] = target['pos_batch'].cuda()
            if args.sample_with_angle:
                target['angle_batch'] = target['angle_batch'].cuda()
            if args.target_speed > 0:
                target['speed_batch'] = target['speed_batch'].cuda()
            if args.target_dist > 0:
                target['dist_batch'] = target['dist_batch'].cuda()

    weight = (0.97 ** np.arange(args.pred_step)).reshape((1, args.pred_step, 1))
    weight = Variable(torch.from_numpy(weight).float().cuda()).repeat(batch_size, 1, 1)
    output = net(imgs, actions, hidden=hidden, cell=cell, training=False, action_var=action_var)

    loss = 0

    # if args.target_dist > 0:
    #     dist_loss = torch.sqrt(nn.MSELoss()(output['dist'], target['dist_batch']))
    #     loss += dist_loss
    # elif args.sample_with_distance:
    #     if args.sample_based_planning:
    #         dist_ls = (output['dist'].view(-1, args.pred_step, 1) * weight).sum(-1).sum(-1)
    #     else:
    #         dist_ls = (output['dist'].view(-1, args.pred_step, 1) * weight).sum()
    #     loss -= dist_ls

    if args.sample_with_collision:
        if 'torcs' in args.env:
            coll_ls = -torch.round(output['coll_prob'][:, :, 0]) * output['dist'].view(-1, args.pred_step) + torch.round(output['coll_prob'][:, :, 1]) * 20.0
        elif 'carla' in args.env:
            coll_ls = -torch.round(output['coll_prob'][:, :, 0]) * output['speed'].view(-1, args.pred_step) + torch.round(output['coll_prob'][:, :, 1]) * 15.0
        # coll_ls = nn.CrossEntropyLoss(reduce = False)(output['coll_prob'].view(batch_size * args.pred_step, 2), target['coll_batch'])
        # coll_ls = (coll_ls.view(-1, args.pred_step, 1) * output['speed'].view(-1, args.pred_step, 1) * weight).sum()
        if args.sample_based_planning:
            coll_ls = (coll_ls.view(-1, args.pred_step, 1) * weight).sum(-1).sum(-1)
        else:
            coll_ls = (coll_ls.view(-1, args.pred_step, 1) * weight).sum() * 50
        loss += coll_ls

    if args.sample_with_offroad:
        if 'torcs' in args.env:
            off_ls = -torch.round(output['offroad_prob'][:, :, 0]) * output['dist'].view(-1, args.pred_step) + torch.round(output['offroad_prob'][:, :, 1]) * 20.0
        elif 'carla' in args.env:
            off_ls = -torch.round(output['offroad_prob'][:, :, 0]) * output['speed'].view(-1, args.pred_step) + (1 - torch.round(output['offroad_prob'][:, :, 0])) * 15.0
        # off_ls = nn.CrossEntropyLoss(reduce = False)(output['offroad_prob'].view(batch_size * args.pred_step, 2), target['off_batch'])
        # off_ls = (off_ls.view(-1, args.pred_step, 1) * output['speed'].view(-1, args.pred_step, 1) * weight).sum()
        if args.sample_based_planning:
            off_ls = (off_ls.view(-1, args.pred_step, 1) * weight).sum(-1).sum(-1)
        else:
            off_ls = (off_ls.view(-1, args.pred_step, 1) * weight).sum() * 50
        loss += off_ls

    if args.sample_with_pos:
        if args.sample_based_planning:
            pos_loss = torch.sqrt((nn.MSELoss(reduce=False)(torch.exp(output['pos']/10), torch.exp(target['pos_batch']/10)))).sum(-1).sum(-1)
        else:
            pos_loss = torch.sqrt((nn.MSELoss()(torch.exp(output['pos']/10), torch.exp(target['pos_batch']/10))))
        loss += pos_loss

    if args.sample_with_angle:
        if args.sample_based_planning:
            angle_loss = torch.sqrt((nn.MSELoss(reduce=False)(torch.exp(output['angle']), torch.exp(target['angle_batch'])))).sum(-1).sum(-1)
        else:
            angle_loss = torch.sqrt((nn.MSELoss()(torch.exp(output['angle']), torch.exp(target['angle_batch']))))
        loss += angle_loss

    if args.target_speed > 0:
        if args.sample_based_planning:
            speed_loss = torch.sqrt(nn.MSELoss(reduce=False)(output['speed'], target['speed_batch'])).sum(-1).sum(-1)
        else:
            speed_loss = torch.sqrt(nn.MSELoss()(output['speed'], target['speed_batch']))
        loss += speed_loss

    if 'xyz_batch' in target.keys():
        if args.sample_based_planning:
            xyz_loss = torch.sqrt(nn.MSELoss(reduce=False)(output['xyz'], target['xyz_batch'])).sum(-1).sum(-1) / 100.0
        else:
            xyz_loss = torch.sqrt(nn.MSELoss()(output['xyz'], target['xyz_batch'])) / 100.0
        loss += xyz_loss

    return loss


def show_accuracy(output, target, label):
    tn, fp, fn, tp = confusion_matrix(output, target, labels=[0, 1]).ravel()
    print('%s accuracy: %0.2f%%' % (label, (tn + tp) / (tn + fp + fn + tp) * 100.0))


def get_action_loss_test(args, net, imgs, actions, target=None, hidden=None, cell=None, gpu=0):
    batch_size = int(imgs.size()[0])
    if args.continuous:
        batch_size = 1
    if target is None:
        target = dict()
        target['angle_batch'] = Variable(torch.zeros(batch_size, args.pred_step, 1), requires_grad = False)
        if torch.cuda.is_available():
            target['angle_batch'] = target['angle_batch'].cuda()

    weight = (0.99 ** np.arange(args.pred_step)).reshape((1, args.pred_step, 1))
    weight = Variable(torch.from_numpy(weight).float().cuda()).repeat(batch_size, 1, 1)
    output = net(imgs, actions, hidden=hidden, cell=cell)

    loss = 0
    dist_ls = (output['dist'].view(-1, args.pred_step, 1) * weight).sum()
    loss -= 0.1 * dist_ls

    angle_loss = torch.sqrt(nn.MSELoss()(output['angle'], target['angle_batch']))
    loss += angle_loss

    return loss


if __name__ == '__main__':
    class dummy(object):
        def __init__(self):
            self.num_total_act = 3
    prob = torch.ones(3, 3) / 3
    all_actions = generate_action_sample(dummy(), prob, 6, 15, 1)
    one_hot_actions = generate_one_hot_actions(all_actions, 3)
    print(all_actions)
    print(all_actions.size())
    print(one_hot_actions)
    print(one_hot_actions.size())
