import tensorflow as tf
from tensorflow.models.rnn import rnn_cell
from tensorflow.models.rnn import seq2seq
from tensorflow.models.rnn import rnn

import numpy as np

class Model():
    def __init__(self, args, infer=False):
        self.args = args
        if infer:
            args.batch_size = 1
            args.seq_length = 1

        if args.model == 'rnn':
            cell_fn = rnn_cell.BasicRNNCell
        elif args.model == 'gru':
            cell_fn = rnn_cell.GRUCell
        elif args.model == 'lstm':
            cell_fn = rnn_cell.BasicLSTMCell
        else:
            raise Exception("model type not supported: {}".format(args.model))

        cell = cell_fn(args.rnn_size)

        self.cell = cell = rnn_cell.MultiRNNCell([cell] * args.num_layers)

        self.input_data = tf.placeholder(tf.int32, [args.batch_size, args.seq_length])
        self.eps = tf.placeholder(tf.float32, [args.batch_size, 4*args.rnn_size])
        self.initial_state = cell.zero_state(args.batch_size, tf.float32)

        with tf.variable_scope('rnnlm'):
            softmax_w = tf.get_variable("softmax_w", [args.rnn_size, args.vocab_size])
            softmax_b = tf.get_variable("softmax_b", [args.vocab_size])
            with tf.device("/cpu:0"):
                embedding = tf.get_variable("embedding", [args.vocab_size, args.rnn_size])
                inputs = tf.split(1, args.seq_length,
                        tf.nn.embedding_lookup(embedding, self.input_data))
                inputs = [tf.squeeze(input_, [1]) for input_ in inputs]

        def loop(prev, _):
            prev = tf.nn.xw_plus_b(prev, softmax_w, softmax_b)
            prev_symbol = tf.stop_gradient(tf.argmax(prev, 1))
            return tf.nn.embedding_lookup(embedding, prev_symbol)

        outputs, states = rnn.rnn(cell, inputs, dtype=tf.float32)
        self.h = states[-1]
        with tf.variable_scope('rnnlm'):
            mu_w = tf.get_variable("mu_w", [4*args.rnn_size, 4*args.rnn_size])
            mu_b = tf.get_variable("mu_b", [4*args.rnn_size])
            sigma_w = tf.get_variable("sigma_w", [4*args.rnn_size, 4*args.rnn_size])
            sigma_b = tf.get_variable("sigma_b", [4*args.rnn_size])

        self.mu = tf.nn.xw_plus_b(self.h, mu_w, mu_b)
        self.log_sigma = 0.5*tf.nn.xw_plus_b(self.h, sigma_w, sigma_b)
        self.z = self.mu + tf.exp(self.log_sigma) * self.eps
        outputs, states = seq2seq.rnn_decoder(inputs, self.z, cell,
                loop_function=loop if infer else None, scope='rnnlm')
        output = tf.reshape(tf.concat(1, outputs), [-1, args.rnn_size])
        self.logits = tf.nn.xw_plus_b(output, softmax_w, softmax_b)
        self.probs = tf.nn.softmax(self.logits)
        loss = seq2seq.sequence_loss_by_example([self.logits],
                [tf.reshape(self.input_data, [-1])],
                [tf.ones([args.batch_size * args.seq_length])],
                args.vocab_size)
        self.prior_cost = 0.5 * tf.reduce_sum(- 1 - 2*self.log_sigma +
                tf.pow(self.mu, 2) + tf.exp(2*self.log_sigma)) / args.batch_size
        self.recons_cost = tf.reduce_sum(loss) / args.seq_length / args.batch_size
        self.cost = self.recons_cost + self.prior_cost
        self.final_state = states[-1]
        self.lr = tf.Variable(0.0, trainable=False)
        tvars = tf.trainable_variables()
        grads, _ = tf.clip_by_global_norm(tf.gradients(self.cost, tvars),
                args.grad_clip)
        optimizer = tf.train.AdamOptimizer(self.lr)
        self.train_op = optimizer.apply_gradients(zip(grads, tvars))

    def sample(self, sess, chars, vocab, num=200, prime='The '):
        state = self.cell.zero_state(1, tf.float32).eval()
        for char in prime[:-1]:
            x = np.zeros((1, 1))
            x[0, 0] = vocab[char]
            feed = {self.input_data: x, self.initial_state:state}
            [state] = sess.run([self.final_state], feed)

        ret = prime
        char = prime[-1]
        for n in xrange(num):
            x = np.zeros((1, 1))
            x[0, 0] = vocab[char]
            feed = {self.input_data: x, self.initial_state:state}
            [probs, state] = sess.run([self.probs, self.final_state], feed)
            p = probs[0]
            sample = int(np.random.choice(len(p), p=p))
            pred = chars[sample]
            ret += pred
            char = pred
        return ret


