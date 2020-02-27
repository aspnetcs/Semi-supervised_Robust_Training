# based on https://github.com/tensorflow/models/tree/master/resnet
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import numpy as np
import tensorflow as tf

import stadv
class Model(object):
  """ResNet model."""

  def __init__(self, config, attack=False):
    """ResNet constructor.
    """
    self._build_model(config.filters,
                      pad_mode=config.pad_mode,
                      pad_size=config.pad_size,
                      attack=attack)

  def add_internal_summaries(self):
    pass

  def _stride_arr(self, stride):
    """Map a stride scalar to the stride array for tf.nn.conv2d."""
    return [1, stride, stride, 1]

  def _build_model(self, filters, pad_mode='CONSTANT', pad_size=32, attack=False):
    """Build the core model within the graph."""
    with tf.variable_scope('input'):

      self.x_input = tf.placeholder(tf.float32, shape=[None, 28, 28, 1])
      self.y_input = tf.placeholder(tf.int64, shape=[None])

      

      self.y_pred_input = tf.placeholder(tf.float32, shape=[None, 10])

      self.transform = tf.placeholder(tf.float32, shape=[None, 3])

      self.weights = tf.placeholder(tf.float32, shape=None)
      self.kl_weights = tf.placeholder(tf.float32, shape=None)

      trans_x, trans_y, rot = tf.unstack(self.transform, axis=1)
      rot *= np.pi / 180 # convert degrees to radians

      self.is_training = tf.placeholder(tf.bool)

      x = self.x_input
       
      x = tf.pad(x, [[0,0], [16,16], [16,16], [0,0]], pad_mode)
      #rotate and translate image
      ones = tf.ones(shape=tf.shape(trans_x))
      zeros = tf.zeros(shape=tf.shape(trans_x))
      trans = tf.stack([ones,  zeros, -trans_x,
                        zeros, ones,  -trans_y,
                        zeros, zeros], axis=1)
      x = tf.contrib.image.rotate(x, rot, interpolation='BILINEAR')
      x = tf.contrib.image.transform(x, trans, interpolation='BILINEAR')
      x = tf.image.resize_image_with_crop_or_pad(x, pad_size, pad_size)

      # everything below this point is generic (independent of spatial attacks)
      self.x_image = x
      x = tf.map_fn(lambda img: tf.image.per_image_standardization(img), x)
      if attack:
        self.flows = tf.placeholder(tf.float32, [None, 2, 28, 28], name='flows')
        self.perturbed_images = stadv.layers.flow_st(x, self.flows, 'NHWC')
        x = self.perturbed_images
      # x = self._conv('init_conv', x, 3, 3, 16, self._stride_arr(1))
    # strides = [1, 2, 2]
    # activate_before_residual = [True, False, False]
    # res_func = self._residual

    # with tf.variable_scope('unit_1_0'):
    #   x = res_func(x, filters[0], filters[1], self._stride_arr(strides[0]),
    #                activate_before_residual[0])
    # for i in range(1, 5):
    #   with tf.variable_scope('unit_1_%d' % i):
    #     x = res_func(x, filters[1], filters[1], self._stride_arr(1), False)

    # with tf.variable_scope('unit_2_0'):
    #   x = res_func(x, filters[1], filters[2], self._stride_arr(strides[1]),
    #                activate_before_residual[1])
    # for i in range(1, 5):
    #   with tf.variable_scope('unit_2_%d' % i):
    #     x = res_func(x, filters[2], filters[2], self._stride_arr(1), False)

    # with tf.variable_scope('unit_3_0'):
    #   x = res_func(x, filters[2], filters[3], self._stride_arr(strides[2]),
    #                activate_before_residual[2])
    # for i in range(1, 5):
    #   with tf.variable_scope('unit_3_%d' % i):
    #     x = res_func(x, filters[3], filters[3], self._stride_arr(1), False)

    # with tf.variable_scope('unit_last'):
    #   x = self._batch_norm('final_bn', x)
    #   x = self._relu(x, 0.1)
    #   x = self._global_avg_pool(x)

    x = tf.layers.conv2d(
        inputs=x,
        filters=32,
        kernel_size=[3, 3],
        padding="same",
        activation=tf.nn.relu
    )
    x = tf.layers.conv2d(
        inputs=x,
        filters=32,
        kernel_size=[3, 3],
        padding="same",
        activation=tf.nn.relu
    )
    x = tf.layers.max_pooling2d(inputs=x, pool_size=[2, 2], strides=2)
    x = tf.layers.conv2d(
        inputs=x,
        filters=64,
        kernel_size=[3, 3],
        padding="same",
        activation=tf.nn.relu
    )
    x = tf.layers.conv2d(
        inputs=x,
        filters=64,
        kernel_size=[3, 3],
        padding="same",
        activation=tf.nn.relu
    )
    x = tf.layers.max_pooling2d(inputs=x, pool_size=[2, 2], strides=2)
    x = tf.reshape(x, [-1, 7 * 7 * 64])
    # logits = tf.layers.dense(inputs=x, units=10)

    # uncomment to add and extra fc layer
    #with tf.variable_scope('unit_fc'):
    #  self.pre_softmax = self._fully_connected(x, 1024)
    #  x = self._relu(x, 0.1)

    with tf.variable_scope('logit'):
      self.pre_softmax = self._fully_connected(x, 10)
      self.softmax = tf.nn.softmax(self.pre_softmax)

    self.predictions = tf.argmax(self.pre_softmax, 1)
    self.correct_prediction = tf.equal(self.predictions, self.y_input)
    self.num_correct = tf.reduce_sum(
        tf.cast(self.correct_prediction, tf.int64))
    self.accuracy = tf.reduce_mean(
        tf.cast(self.correct_prediction, tf.float32))

    with tf.variable_scope('costs'):
      self.y_xent = tf.nn.sparse_softmax_cross_entropy_with_logits(
          logits=self.pre_softmax, labels=self.y_input)\
          * self.weights
      self.xent = tf.reduce_sum(self.y_xent, name='y_xent')
      self.mean_xent = tf.reduce_mean(self.y_xent)
      self.weight_decay_loss = self._decay()

      self.y_kl = - tf.reduce_sum(tf.log(tf.clip_by_value(self.softmax, clip_value_min=1e-8, clip_value_max=1)) * self.y_pred_input, reduction_indices=-1) * self.kl_weights
      self.mean_kl = tf.reduce_mean(self.y_kl)

  def _batch_norm(self, name, x):
    """Batch normalization."""
    with tf.name_scope(name):
      return tf.contrib.layers.batch_norm(
          inputs=x,
          decay=.9,
          center=True,
          scale=True,
          activation_fn=None,
          updates_collections=None,
          is_training=self.is_training)

  def _residual(self, x, in_filter, out_filter, stride,
                activate_before_residual=False):
    """Residual unit with 2 sub layers."""
    if activate_before_residual:
      with tf.variable_scope('shared_activation'):
        x = self._batch_norm('init_bn', x)
        x = self._relu(x, 0.1)
        orig_x = x
    else:
      with tf.variable_scope('residual_only_activation'):
        orig_x = x
        x = self._batch_norm('init_bn', x)
        x = self._relu(x, 0.1)

    with tf.variable_scope('sub1'):
      x = self._conv('conv1', x, 3, in_filter, out_filter, stride)

    with tf.variable_scope('sub2'):
      x = self._batch_norm('bn2', x)
      x = self._relu(x, 0.1)
      x = self._conv('conv2', x, 3, out_filter, out_filter, [1, 1, 1, 1])

    with tf.variable_scope('sub_add'):
      if in_filter != out_filter:
        orig_x = tf.nn.avg_pool(orig_x, stride, stride, 'VALID')
        orig_x = tf.pad(
            orig_x, [[0, 0], [0, 0], [0, 0],
                     [(out_filter-in_filter)//2, (out_filter-in_filter)//2]])
      x += orig_x

    tf.logging.debug('image after unit %s', x.get_shape())
    return x

  def _decay(self):
    """L2 weight decay loss."""
    costs = []
    for var in tf.trainable_variables():
      if var.op.name.find('DW') >= 0:
        costs.append(tf.nn.l2_loss(var))
    return tf.add_n(costs)

  def _conv(self, name, x, filter_size, in_filters, out_filters, strides):
    """Convolution."""
    with tf.variable_scope(name):
      n = filter_size * filter_size * out_filters
      kernel = tf.get_variable(
          'DW', [filter_size, filter_size, in_filters, out_filters],
          tf.float32, initializer=tf.random_normal_initializer(
              stddev=np.sqrt(2.0/n)))
      return tf.nn.conv2d(x, kernel, strides, padding='SAME')

  def _relu(self, x, leakiness=0.0):
    """Relu, with optional leaky support."""
    return tf.where(tf.less(x, 0.0), leakiness * x, x, name='leaky_relu')

  def _fully_connected(self, x, out_dim):
    """FullyConnected layer for final output."""
    num_non_batch_dimensions = len(x.shape)
    prod_non_batch_dimensions = 1
    for ii in range(num_non_batch_dimensions - 1):
      prod_non_batch_dimensions *= int(x.shape[ii + 1])
    x = tf.reshape(x, [tf.shape(x)[0], -1])
    w = tf.get_variable(
        'DW', [prod_non_batch_dimensions, out_dim],
        initializer=tf.initializers.variance_scaling())
    b = tf.get_variable('biases', [out_dim],
                        initializer=tf.constant_initializer())
    return tf.nn.xw_plus_b(x, w, b)

  def _global_avg_pool(self, x):
    assert x.get_shape().ndims == 4
    return tf.reduce_mean(x, [1, 2])
