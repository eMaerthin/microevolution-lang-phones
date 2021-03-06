import json
import logging

import numpy as np
from scipy.signal import spectrogram

from decorators import check_if_already_done
from format_converters import get_segment
from schemas import *
from chains.formants import Formants
from chains.phoneme import Phoneme
logger = logging.getLogger()


class Spectrogram(Formants):
    requirements = [Phoneme]
    abstract_class = False


    @staticmethod
    def result_filename(json_path):
        return f'{json_path[:-5]}_spectrogram_result.json'

    @staticmethod
    def filename_prerequisites():
        def audio_path(json_path):
            return f'{json_path[:-5]}_audio.mp4'
        return [audio_path, Phoneme.result_filename]

    @staticmethod
    def result_filename_postprocessed(json_path):
        return f'{json_path[:-5]}_spectrogram_result.csv'

    def compute_spectrograms(self, segments_path, phonemes_result_path, spectrogram_result_path,
                             phoneme_len=2048, ignore_shorter_phonemes=True):
        @check_if_already_done(spectrogram_result_path, validator=lambda x: x)
        def store_spectrograms(segments_path, phonemes_result_path, spectrogram_result_path):
            wav = get_segment(segments_path, 'wav')
            frequency = wav.frame_rate
            schema = DecoderOutputSchema()
            with open(phonemes_result_path, 'r') as f:
                logger.info(f'phonemes_result_path: {phonemes_result_path}')
                json_file = json.load(f)
                phonemes_result = schema.load(json_file)
                phonemes_info = [info for info in phonemes_result['segment_info']
                                 if info['word'] not in self.blacklisted_phonemes]
                spectrograms_result = []
                for info in phonemes_info:
                    start, stop = (1000 * info['start'], 1000 * info['end'])
                    segment = np.array(wav[start:stop].get_array_of_samples())
                    freq, t, Sxx = spectrogram(segment, fs=frequency, window=('kaiser', 4.0),
                                               nperseg=min(phoneme_len, len(segment)), noverlap=1)
                    if len(freq) != phoneme_len // 2 + 1 and ignore_shorter_phonemes:
                        continue
                    for i in range(len(t)):
                        ith_spectrogram = Sxx[:, i]
                        spectrogram_result = {'t': t[i], 'i': i, 'len_t': len(t), 'len_freq': len(freq),
                                              'freq_delta': freq[1] - freq[0], 'signal': ith_spectrogram, **info}
                        spectrograms_result.append(spectrogram_result)
                spectrograms = PhonemesSpectrogramsSchema()
                spectrograms_dict = {'spectrograms_info': spectrograms_result}
                result = spectrograms.dumps(spectrograms_dict)
                with open(spectrogram_result_path, 'w') as result_f:
                    result_f.write(result)
                    return True
        store_spectrograms(segments_path, phonemes_result_path, spectrogram_result_path)

    def compute_target(self, segments_path, phonemes_path, series_json_path):
        spectrogram_result_path = self.result_filename(series_json_path)
        self.compute_spectrograms(segments_path, phonemes_path, spectrogram_result_path)
        logger.info(f'spectrogram result path: {spectrogram_result_path}')
