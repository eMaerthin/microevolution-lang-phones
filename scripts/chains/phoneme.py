import json
import logging
from os.path import join
from pocketsphinx.pocketsphinx import Decoder

from audio_processors import (audio_and_segment_paths, resolve_audio_path)
from decorators import check_if_already_done
from schemas import (PocketsphinxSegmentSchema, PocketsphinxHypothesisSchema, DecoderOutputSchema)

from chain import Chain
from chains.preprocess import Preprocess

MODEL_DIR = "../thirdparty/pocketsphinx/model"
logger = logging.getLogger()


class Phoneme(Chain):
    allow_sample_layer_concurrency = True
    abstract_class = False

    requirements = [Preprocess]

    def __init__(self):
        self.decoder = None
        super().__init__()

    @staticmethod
    def sample_result_filename(out_sample_path):
        return f'{out_sample_path[:-5]}_phoneme_result.json'

    def _compute_phonemes(self, segments_path, phonemes_result_path):
        """

        :param segments_path:
        :param phonemes_result_path:
        :return:
        """
        model_dir = self.process_settings.get('model_dir', MODEL_DIR)
        decoder_hmm = self.process_settings.get('decoder_hmm', 'en-us/en-us')
        decoder_allphone = self.process_settings.get('decoder_allphone',
                                                     'en-us/en-us-phone.lm.bin')
        decoder_dict = self.process_settings.get('decoder_dict',
                                                 'en-us/cmudict-en-us.dict')
        decoder_lw = self.process_settings.get('decoder_lw', 2.0)
        decoder_pip = self.process_settings.get('decoder_pip', 0.3)
        decoder_beam = self.process_settings.get('decoder_beam', 1e-200)
        decoder_pbeam = self.process_settings.get('decoder_pbeam', 1e-20)
        decoder_mmap = self.process_settings.get('decoder_mmap', False)
        decoder_stream_buf_size = self.process_settings.get('decoder_stream_buf_size',
                                                            8192)
        pprint_indent = self.process_settings.get('pprint_indent', 4)
        hypothesis = PocketsphinxHypothesisSchema()
        ph_info = PocketsphinxSegmentSchema()

        def _get_decoder_results():
            self.decoder.end_utt()
            segment = [ph_info.dump(dict(word=seg.word,
                                         start=seg.start_frame / 100,
                                         end=seg.end_frame / 100,
                                         prob=seg.prob))
                       for seg in self.decoder.seg()]
            hyp = self.decoder.hyp()
            hyp_dict = dict(best_score=hyp.best_score,
                            hypstr=hyp.hypstr, prob=hyp.prob)
            hyp_result = hypothesis.dump(hyp_dict)
            return hyp_result, segment

        @check_if_already_done(phonemes_result_path)
        def recognize_phonemes(segments_path, phonemes_result_path):

            # Create a decoder with certain model
            config = Decoder.default_config()
            config.set_string('-hmm', join(model_dir, decoder_hmm))
            config.set_string('-allphone', join(model_dir, decoder_allphone))
            config.set_string('-dict', join(model_dir, decoder_dict))
            config.set_float('-lw', decoder_lw)
            config.set_float('-pip', decoder_pip)
            config.set_float('-beam', decoder_beam)
            config.set_float('-pbeam', decoder_pbeam)
            config.set_boolean('-mmap', decoder_mmap)
            hyps=[]
            segs=[]
            self.decoder = Decoder(config)
            with open(segments_path, 'rb') as stream:
                in_speech_buffer = False
                self.decoder.start_utt()
                while True:
                    buf = stream.read(decoder_stream_buf_size)
                    if buf:
                        self.decoder.process_raw(buf, False, False)
                        if self.decoder.get_in_speech() != in_speech_buffer:
                            in_speech_buffer = self.decoder.get_in_speech()
                            if not in_speech_buffer:
                                hyp_result, segment = _get_decoder_results()
                                segs += segment

                                hyps.append(hyp_result)
                                self.decoder.start_utt()
                    else:
                        if in_speech_buffer:
                            hyp_result, segment = _get_decoder_results()
                            segs += segment

                            hyps.append(hyp_result)
                        break
            phonemes_dict = dict(hypotheses=hyps, segment_info=segs)
            phonemes_result = DecoderOutputSchema().dumps(phonemes_dict)
            with open(phonemes_result_path, 'w') as f:
                f.write(phonemes_result)

        recognize_phonemes(segments_path, phonemes_result_path)

        schema = DecoderOutputSchema()
        with open(phonemes_result_path, 'r') as f:
            logger.info(f'phonemes_result_path: {phonemes_result_path}')
            json_file = json.load(f)
            result = schema.load(json_file)
            logger.debug(json.dumps(result, indent=pprint_indent))

    def sample_layer(self, subject, sample_json_filename, sample_settings):
        url = sample_settings.get('url')
        datatype = sample_settings.get('datatype')

        output_path_pattern = join(self.results_dir, subject, sample_json_filename)
        phonemes_result_file = self.sample_result_filename(output_path_pattern)
        logger.info(f'phonemes result file: {phonemes_result_file}')
        audio_path = resolve_audio_path(url, datatype, output_path_pattern)
        _, segments_path = audio_and_segment_paths(audio_path, use_original_frequency=False, audio_format='wav')
        self._compute_phonemes(segments_path, phonemes_result_file)
