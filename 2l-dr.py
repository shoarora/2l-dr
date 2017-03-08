# import shit
# get flags and args
# initialize data
# initialize model
# train/summarize
import argparse

from model import Encoder, Decoder, Summarizer


def setup_argparse():
    parser = argparse.ArgumentParser()
    parser.add_argument('--train', action='store_true')
    parser.add_argument('--sum', action='store_true')
    parser.add_argument('--data_path')
    parser.add_argument('--input_path')
    parser.add_argument('--sess_name')
    return parser

if __name__ == '__main__':
    parser = setup_argparse()
    args = parser.parse_args()
    # encoder = Encoder()
    # decoder = Decoder()
    encoder = None
    decoder = None
    if args.train:
        summarizer = Summarizer(encoder, decoder, args.data_path,
                                True, args.sess_name)
        summarizer.train()
    if args.sum:
        summarizer = Summarizer(encoder, decoder, args.data_path,
                                False, args.sess_name)
        summarizer.summarize(args.input_path)
