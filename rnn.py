import copy

import tensorflow as tf


def seq2seq(encoder_inputs,
            decoder_inputs,
            cell,
            num_encoder_symbols,
            num_decoder_symbols,
            embedding_size,
            embeddings,
            output_projection=None,
            feed_previous=None):

    def seq2seq_f(feed_prev):
        with tf.variable_scope('rnn_seq2seq'):
            # encode
            encoder_cell = copy.deepcopy(cell)
            embedded_enc_input = tf.nn.embedding_lookup(embeddings,
                                                        encoder_inputs)
            attention_states, encoder_state = tf.nn.dynamic_rnn(
                                                encoder_cell,
                                                embedded_enc_input,
                                                dtype=tf.float32)

            # decode
            embedded_dec_input = [tf.nn.embedding_lookup(embeddings, d)
                                  for d in decoder_inputs]
            loop_function = tf.nn.seq2seq._extract_argmax_and_embed(
                                embeddings,
                                output_projection,
                                True) \
                if feed_prev else None
            return tf.nn.seq2seq.attention_decoder(
                embedded_dec_input,
                encoder_state,
                attention_states,
                cell,
                loop_function=loop_function)[0]

    def seq_with_previous():
        with tf.variable_scope(tf.get_variable_scope(), reuse=None):
            return seq2seq_f(True)

    def seq_without_previous():
        with tf.variable_scope(tf.get_variable_scope(), reuse=True):
            return seq2seq_f(False)

    return tf.cond(feed_previous, seq_with_previous, seq_without_previous), None
