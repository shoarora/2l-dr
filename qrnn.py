'''QRNN class and functions for 2l-dr: headline generation (take 2)
implements all the layer functions and operations
for a Quasi-RNN https://arxiv.org/pdf/1611.01576.pdf

Also implements the seq2seq function for tf.nn.model_with_buckets()

There are some eval_* variants of some functions, which were written to run
the decode step during training.
'''

import tensorflow as tf
from tensorflow.python.util import nest


class QRNN(object):
    def _init_vars(self):
        '''  initialize tf vars.  i feel like this is an incorrect use of
             scoping but i couldn't really figure out how else to do it  '''
        for i in xrange(self.num_layers):
            input_shape = self.embedding_size if i == 0 else \
                self.num_convs
            with tf.variable_scope("QRNN/"+self.name +
                                   "/Variable/Convolution/"+str(i),
                                   reuse=False):
                filter_shape = self._get_filter_shape(input_shape)
                tf.get_variable('W', filter_shape,
                                initializer=self.initializer, dtype=tf.float32)
                tf.get_variable('b', [self.num_convs*3],
                                initializer=self.initializer, dtype=tf.float32)
            with tf.variable_scope("QRNN/"+self.name +
                                   "/Variable/Conv_w_enc_out/"+str(i),
                                   reuse=False):
                v_shape = (self.num_convs, self.num_convs*3)
                tf.get_variable('V', v_shape,
                                initializer=self.initializer, dtype=tf.float32)
                tf.get_variable('b', [self.num_convs*3],
                                initializer=self.initializer, dtype=tf.float32)
                filter_shape = self._get_filter_shape(input_shape)
                tf.get_variable('W', filter_shape,
                                initializer=self.initializer, dtype=tf.float32)
        with tf.variable_scope('QRNN/'+self.name +
                               '/Conv_with_attention/', reuse=False):
            attn_weight_shape = [self.num_convs, self.num_convs]
            tf.get_variable('W_k', attn_weight_shape,
                            initializer=self.initializer, dtype=tf.float32)
            tf.get_variable('W_c', attn_weight_shape,
                            initializer=self.initializer, dtype=tf.float32)
            tf.get_variable('b_o', [self.num_convs],
                            initializer=self.initializer, dtype=tf.float32)

    def __init__(self, num_symbols, seq_length,
                 embedding_size, num_layers, conv_size, num_convs,
                 output_projection=None, name=''):
        '''  init qrnn class  '''
        self.num_symbols = num_symbols
        self.seq_length = seq_length
        self.embedding_size = embedding_size
        self.num_layers = num_layers
        self.conv_size = conv_size
        self.num_convs = num_convs
        self.output_projection = output_projection
        self.initializer = tf.random_normal_initializer()
        self.name = name
        self._init_vars()

    def get_embeddings(self, embeddings, word_ids):
        '''  get word embeddings  '''
        if word_ids is None:
            return None
        return tf.nn.embedding_lookup(embeddings, word_ids)

    def fo_pool(self, Z, F, O, seq_len=None, c_prev=None):
        ''' fo-pooling function defined in Bradbury et al. on QRNNs
            very reminiscent of LSTM gates'''
        if seq_len is None:
            seq_len = self.seq_length
        # Z, F, O dims: [batch_size, sequence_length, num_convs]
        H = [tf.fill(tf.pack([tf.shape(Z)[0], tf.shape(Z)[2]]), 0.0)]
        if c_prev is not None:
            C = [c_prev]
        else:
            C = [tf.fill(tf.pack([tf.shape(Z)[0], tf.shape(Z)[2]]), 0.0)]
        # recurrent definition, must be computed one timestep at a time
        for i in range(1, seq_len):
            c_i = tf.mul(F[:, i, :], C[-1]) + \
                  tf.mul(1-F[:, i, :], Z[:, i, :])
            # C[:, i, :] = c_i
            C.append(c_i)
            h_i = tf.mul(O[:, i, :], c_i)
            # H[:, i, :] = h_i
            H.append(tf.squeeze(h_i))
        # i think we want output [batch, seq_len, num_convs]
        return tf.reshape(tf.pack(H), tf.shape(Z)), C[-1]

    def eval_fo_pool(self, Z, F, O, seq_len, c_prev=None):
        '''  fo-pool variant for use during evaluation  '''
        # Z, F, O dims: [batch_size, sequence_length, num_convs]
        H = []
        C = [c_prev]
        for i in range(0, seq_len):
            c_i = tf.mul(F[:, i, :], C[-1]) + \
                  tf.mul(1-F[:, i, :], Z[:, i, :])
            # C[:, i, :] = c_i
            C.append(c_i)
            h_i = tf.mul(O[:, i, :], c_i)
            # H[:, i, :] = h_i
            H.append(tf.squeeze(h_i))
        # i think we want output [batch, seq_len, num_convs]
        return tf.reshape(tf.pack(H), tf.shape(Z)), C[-1]

    # def f_pool(self, Z, F, sequence_length):
    #     # Z, F dims: [batch_size, sequence_length, num_convs]
    #     H = tf.fill(tf.shape(Z), 0)
    #     for i in range(1, self.seq_length):
    #         H[:, i, :] = tf.mul(F[:, i, :], H[:, i-1, :]) + \
    #                      tf.mul(1-F[:, i, :])
    #     return np.array(H)

    def _get_filter_shape(self, input_shape):
        '''  set up dimensions for convolution filter  '''
        return [self.conv_size, input_shape, 1, self.num_convs*3]

    # convolution dimension results maths
    # out_height = ceil(float(in_height - filter_height + 1) /
    #                   float(strides[1])) = sequence_length
    # out_width  = ceil(float(in_width - filter_width + 1) /
    #                   float(strides[2])) = 1
    # in_height = sequence_length + filter_height - 1
    # filter_height = conv_size
    # in_width = embedding_size
    # filter_width = embedding_size

    def conv_layer(self, layer_id, inputs, input_shape, center_conv=False):
        '''  execute a convolution over inputs.  default is to used a masked
             convolution.  '''
        with tf.variable_scope("QRNN/"+self.name +
                               "/Variable/Convolution/"+str(layer_id),
                               reuse=True):
            filter_shape = self._get_filter_shape(input_shape)
            W = tf.get_variable('W', filter_shape,
                                initializer=self.initializer, dtype=tf.float32)
            b = tf.get_variable('b', [self.num_convs*3],
                                initializer=self.initializer, dtype=tf.float32)
            if not center_conv:
                num_pads = self.conv_size - 1
                # input dims ~should~ now be [batch_size, sequence_length,
                #                             embedding_size, 1]
                padded_input = tf.pad(tf.expand_dims(inputs, -1),
                                      [[0, 0], [num_pads, 0],
                                       [0, 0], [0, 0]],
                                      "CONSTANT")
            else:
                assert self.conv_size % 2 == 1
                num_pads = (self.conv_size - 1) / 2
                padded_input = tf.pad(tf.expand_dims(inputs, -1),
                                      [[0, 0], [num_pads, num_pads],
                                       [0, 0], [0, 0]],
                                      "CONSTANT")

            conv = tf.nn.conv2d(
                padded_input,
                W,
                strides=[1, 1, 1, 1],
                padding="VALID",
                name="conv") + b
            # conv dims: [batch_size, sequence_length,
            #             1, num_convs*3]
            # squeeze out 3rd D
            # split 4th (now 3rd) dim into 3
            Z, F, O = tf.split(2, 3, tf.squeeze(conv, [2]))
            return self.fo_pool((tf.tanh(Z)), tf.sigmoid(F), tf.sigmoid(O))

    def conv_with_encode_output(self, layer_id, h_t, inputs,
                                input_shape, pool=True,
                                seq_len=None):
        '''  execute a convolution, also feeding in a previous
             output before the pooling step.
             option to disable pooling: used in conv_with_attention'''
        if seq_len is None:
            seq_len = self.seq_length
        pooling = self.fo_pool if pool else lambda x, y, z, seq_len: (x, y, z)
        with tf.variable_scope("QRNN/"+self.name +
                               "/Variable/Conv_w_enc_out/"+str(layer_id),
                               reuse=True):
            v_shape = (self.num_convs, self.num_convs*3)
            V = tf.get_variable('V', v_shape,
                                initializer=self.initializer, dtype=tf.float32)
            b = tf.get_variable('b', [self.num_convs*3],
                                initializer=self.initializer, dtype=tf.float32)

            filter_shape = self._get_filter_shape(input_shape)
            W = tf.get_variable('W', filter_shape,
                                initializer=self.initializer, dtype=tf.float32)

            num_pads = self.conv_size - 1
            h_tV = tf.matmul(h_t, V)
            Z_v, F_v, O_v = tf.split(1, 3, h_tV)

            # input dims ~should~ now be [batch_size, sequence_length,
            #                             embedding_size, 1]
            padded_input = tf.pad(tf.expand_dims(inputs, -1),
                                  [[0, 0], [num_pads, 0],
                                   [0, 0], [0, 0]],
                                  "CONSTANT")
            conv = tf.nn.conv2d(
                padded_input,
                W,
                strides=[1, 1, 1, 1],
                padding="VALID",
                name="conv") + b
            # conv dims: [batch_size, sequence_length,
            #             1, num_convs*3]
            # squeeze out 3rd D
            # split 4th (now 3rd) dim into 3
            Z_conv, F_conv, O_conv = tf.split(2, 3, tf.squeeze(conv))
            Z = Z_conv + tf.expand_dims(Z_v, 1)
            F = F_conv + tf.expand_dims(F_v, 1)
            O = O_conv + tf.expand_dims(O_v, 1)
            return pooling(tf.tanh(Z), tf.sigmoid(F), tf.sigmoid(O), seq_len)

    def conv_with_attention(self, layer_id, encode_outputs, inputs,
                            input_shape, seq_len=None):
        '''  perform a convolution step with soft attention  '''
        if seq_len is None:
            seq_len = self.seq_length
        h_t = tf.squeeze(encode_outputs[-1][:, -1, :])
        Z, F, O = self.conv_with_encode_output(layer_id, h_t, inputs,
                                               input_shape, pool=False)
        # input dim [batch, seq_len, num_convs]
        with tf.variable_scope('QRNN/'+self.name +
                               '/Conv_with_attention/', reuse=True):
            attn_weight_shape = [self.num_convs, self.num_convs]

            W_k = tf.get_variable('W_k', attn_weight_shape,
                                  initializer=self.initializer,
                                  dtype=tf.float32)
            W_c = tf.get_variable('W_c', attn_weight_shape,
                                  initializer=self.initializer,
                                  dtype=tf.float32)
            b_o = tf.get_variable('b_o', [self.num_convs],
                                  initializer=self.initializer,
                                  dtype=tf.float32)

            # calculate attention
            enc_final_state = encode_outputs[-1]
            H = [tf.fill(tf.pack([tf.shape(Z)[0], tf.shape(Z)[2]]), 0.0)]
            C = [tf.fill(tf.pack([tf.shape(Z)[0], tf.shape(Z)[2]]), 0.0)]
            for i in range(1, seq_len):
                c_i = tf.mul(F[:, i, :], C[-1]) + \
                      tf.mul(1-F[:, i, :], Z[:, i, :])
                C.append(c_i)
                # C_i dim [batch, num_convs]
                # enc_final_state dim [batch, seq_len, num_convs]
                c_dot_h = tf.reduce_sum(tf.mul(tf.expand_dims(c_i, 1),
                                        enc_final_state), axis=2)
                # alpha dim [batch, seq_len]
                alpha = tf.nn.softmax(c_dot_h)
                k_t = tf.mul(tf.expand_dims(alpha, -1), enc_final_state)
                x = tf.matmul(tf.reshape(k_t, [-1, self.num_convs]), W_k)
                x2 = tf.reduce_sum(tf.reshape(x, tf.shape(k_t)), axis=1)
                y = tf.matmul(c_i, W_c)+b_o
                h_i = tf.mul(O[:, i, :], x2+y)
                H.append(tf.squeeze(h_i))
            return tf.reshape(tf.pack(H), tf.shape(Z)), C[-1]

    # def transform_output(self, inputs):
    #     # input dim list of [batch, num_convs]
    #     shape = (self.num_convs, self.num_symbols)
    #     with tf.variable_scope('QRNN/'+self.name+'/Transform_output'):
    #         W = tf.get_variable('W', shape,
    #                             initializer=self.initializer,
    #                             dtype=tf.float32)
    #         b = tf.get_variable('b', [self.num_symbols],
    #                             initializer=self.initializer, d
    #                             type=tf.float32)
    #         # TODO: do efficiently
    #         result = []
    #         for i in inputs:
    #             result.append(tf.nn.xw_plus_b(i, W, b))
    #     return result

    def eval_conv_with_encode_output(self, layer_id, h_t, inputs,
                                     input_shape, c_prev, pool=True):
        seq_len = self.conv_size
        pooling = self.eval_fo_pool if pool else \
            lambda v, w, x, y, z: (v, w, x)
        with tf.variable_scope("QRNN/"+self.name +
                               "/Variable/Conv_w_enc_out/"+str(layer_id),
                               reuse=True):
            v_shape = (self.num_convs, self.num_convs*3)
            V = tf.get_variable('V', v_shape,
                                initializer=self.initializer, dtype=tf.float32)
            b = tf.get_variable('b', [self.num_convs*3],
                                initializer=self.initializer, dtype=tf.float32)

            filter_shape = self._get_filter_shape(input_shape)
            W = tf.get_variable('W', filter_shape,
                                initializer=self.initializer, dtype=tf.float32)

            h_tV = tf.matmul(h_t, V)
            Z_v, F_v, O_v = tf.split(1, 3, h_tV)

            conv = tf.nn.conv2d(
                tf.expand_dims(inputs, -1),
                W,
                strides=[1, 1, 1, 1],
                padding="VALID",
                name="conv") + b
            # conv dims: [batch_size, sequence_length,
            #             1, num_convs*3]
            # squeeze out 3rd D
            # split 4th (now 3rd) dim into 3
            Z_conv, F_conv, O_conv = tf.split(2, 3, tf.squeeze(conv, [2]))
            Z = Z_conv + tf.expand_dims(Z_v, 1)
            F = F_conv + tf.expand_dims(F_v, 1)
            O = O_conv + tf.expand_dims(O_v, 1)
            return pooling(tf.tanh(Z), tf.sigmoid(F),
                           tf.sigmoid(O), seq_len-self.conv_size+1, c_prev)

    def eval_conv_with_attention(self, layer_id, encode_outputs, inputs,
                                 input_shape, c_prev):
        seq_len = self.conv_size
        h_t = tf.squeeze(encode_outputs[-1][:, -1, :])
        Z, F, O = self.eval_conv_with_encode_output(layer_id, h_t, inputs,
                                                    input_shape, c_prev,
                                                    pool=False)
        # input dim [batch, seq_len, num_convs]
        with tf.variable_scope('QRNN/'+self.name +
                               '/Conv_with_attention/', reuse=True):
            attn_weight_shape = [self.num_convs, self.num_convs]

            W_k = tf.get_variable('W_k', attn_weight_shape,
                                  initializer=self.initializer,
                                  dtype=tf.float32)
            W_c = tf.get_variable('W_c', attn_weight_shape,
                                  initializer=self.initializer,
                                  dtype=tf.float32)
            b_o = tf.get_variable('b_o', [self.num_convs],
                                  initializer=self.initializer,
                                  dtype=tf.float32)

            # calculate attention
            enc_final_state = encode_outputs[-1]
            H = []
            C = [c_prev]
            for i in range(0, seq_len-self.conv_size+1):
                c_i = tf.mul(F[:, i, :], C[-1]) + \
                      tf.mul(1-F[:, i, :], Z[:, i, :])
                C.append(c_i)
                # C_i dim [batch, num_convs]
                # enc_final_state dim [batch, seq_len, num_convs]
                c_dot_h = tf.reduce_sum(tf.mul(tf.expand_dims(c_i, 1),
                                        enc_final_state), axis=2)
                # alpha dim [batch, seq_len]
                alpha = tf.nn.softmax(c_dot_h)
                k_t = tf.mul(tf.expand_dims(alpha, -1), enc_final_state)
                x = tf.matmul(tf.reshape(k_t, [-1, self.num_convs]), W_k)
                x2 = tf.reduce_sum(tf.reshape(x, tf.shape(k_t)), axis=1)
                y = tf.matmul(c_i, W_c)+b_o
                h_i = tf.mul(O[:, i, :], x2+y)
                H.append(tf.squeeze(h_i))
            return tf.reshape(tf.pack(H), tf.shape(Z)), C[-1]


def init_encoder_and_decoder(num_encoder_symbols, num_decoder_symbols,
                             enc_seq_length, dec_seq_length,
                             embedding_size, num_layers, conv_size, num_convs,
                             output_projection):
    encoder = QRNN(num_encoder_symbols, enc_seq_length,
                   embedding_size, num_layers, conv_size, num_convs, 'enc')
    decoder = QRNN(num_decoder_symbols, dec_seq_length,
                   embedding_size, num_layers, conv_size, num_convs,
                   output_projection, 'dec')
    return encoder, decoder


def seq2seq_f(encoder, decoder, encoder_inputs, decoder_inputs,
              feed_prev, embeddings, cell, center_conv=False):
    '''  runs an encode-decode step for an QRNNenc + RNNdec model  '''
    # inputs are lists of placeholders, each one is shape [None]
    # self.enc_input_size = len(encoder_inputs)
    # self.dec_input_size = len(decoder_inputs)
    encode_outputs = []
    # pack inputs to be shape [sequence_length, batch_size]
    encoder_inputs = tf.transpose(tf.pack(encoder_inputs))

    # embed to be shape [batch_size, sequence_length, embed_size]
    embedded_enc_inputs = encoder.get_embeddings(embeddings, encoder_inputs)

    # encode with qrnn
    for i in range(encoder.num_layers):
        inputs = embedded_enc_inputs if i == 0 else encode_outputs[-1]
        input_shape = encoder.embedding_size if i == 0 else encoder.num_convs
        encode_outputs.append(encoder.conv_layer(i, inputs, input_shape,
                                                 center_conv)[0])
    encoder_state = tuple([encode_outputs[i][:, -1, :]
                           for i in range(encoder.num_layers)])

    encode_outputs = tf.concat(1, [tf.reverse(e, [False, True, False])
                                   for e in encode_outputs])

    # decode with rnn
    def decode(feed_prev_bool):
        reuse = None if feed_prev_bool else True
        with tf.variable_scope(tf.get_variable_scope(), reuse=reuse):
            loop_function = tf.nn.seq2seq._extract_argmax_and_embed(
                                embeddings,
                                decoder.output_projection,
                                True) if feed_prev_bool else None
            embedded_dec_inputs = [tf.nn.embedding_lookup(embeddings, i)
                                   for i in decoder_inputs]
            outputs, state = tf.nn.seq2seq.attention_decoder(
                embedded_dec_inputs,
                encoder_state,
                encode_outputs,
                cell,
                loop_function=loop_function)
            state_list = [state]
            if nest.is_sequence(state):
                state_list = nest.flatten(state)
            # tf.cond has to return a single value
            return outputs + state_list

    # we want to feed previous input in during testing
    outputs_and_state = tf.cond(feed_prev,
                                lambda: decode(True),
                                lambda: decode(False))
    outputs_len = len(decoder_inputs)
    state_list = outputs_and_state[outputs_len:]
    state = state_list[0]
    if nest.is_sequence(encoder_state):
        state = nest.pack_sequence_as(structure=encoder_state,
                                      flat_sequence=state_list)
    return outputs_and_state[:outputs_len], state
