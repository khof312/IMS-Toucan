import os
import re

import numpy as np
import torch
from torch.nn.utils.rnn import pad_sequence
from transformers import RobertaTokenizerFast, RobertaModel

from Preprocessing.word_embeddings.WordEmbeddingExtractor import WordEmbeddingExtractor
from Preprocessing.TextFrontend import ArticulatoryCombinedTextFrontend
from Preprocessing.TextFrontend import english_text_expansion
from Utility.storage_config import MODELS_DIR


class EmotionRoBERTaWordEmbeddingExtractor(WordEmbeddingExtractor):
    def __init__(self, cache_dir:str ="", device=torch.device("cuda")):
        super().__init__()
        if cache_dir:
            self.cache_dir = cache_dir
        self.tokenizer = RobertaTokenizerFast.from_pretrained('j-hartmann/emotion-english-distilroberta-base', cache_dir=self.cache_dir)
        self.model = RobertaModel.from_pretrained("j-hartmann/emotion-english-distilroberta-base", cache_dir=self.cache_dir).to(device)
        self.model.eval()
        self.device = device
        self.tf = ArticulatoryCombinedTextFrontend(language="en")
        self.merge_tokens = set()

    def encode(self, sentences: list[str]) -> np.ndarray:
        if type(sentences) == str:
            sentences = [sentences]
        # apply spacing
        sentences = [english_text_expansion(sent) for sent in sentences]
        # replace words
        for sent in sentences:
            phone_string = self.tf.get_phone_string(sent)
            if len(phone_string.split()) != len(sent.split()):
                #print("Warning: length mismatch in following sentence")
                #print(sent)
                #print(phone_string)
                #print(len(phone_string.split()))
                self.merge_tokens.update(self.get_merge_tokens(sent))
        # tokenize and encode sentences
        encoded_input = self.tokenizer(sentences, padding=True, return_tensors='pt').to(self.device)
        with torch.no_grad():
            # get all hidden states
            hidden_states = self.model(**encoded_input, output_hidden_states=True).hidden_states
        # stack and sum last 4 layers for each token
        token_embeddings = torch.stack([hidden_states[-4], hidden_states[-3], hidden_states[-2], hidden_states[-1]]).sum(0).squeeze()
        if len(sentences) == 1:
            token_embeddings = token_embeddings.unsqueeze(0)
        word_embeddings_list = []
        lens = []
        for batch_id in range(len(sentences)):
            # get word ids corresponding to token embeddings
            word_ids = encoded_input.word_ids(batch_id)
            word_ids_set = set([word_id for word_id in word_ids if word_id is not None])
            # get ids of hidden states of sub tokens for each word
            token_ids_words = [[t_id for t_id, word_id in enumerate(word_ids) if word_id == w_id] for w_id in word_ids_set]
            # combine hidden states of sub tokens for each word
            word_embeddings = torch.stack([token_embeddings[batch_id, token_ids_word].mean(dim=0) for token_ids_word in token_ids_words])
            # combine word embeddings tokens merged by the phonemizer
            tokens = re.findall(r"[\w']+|[.,!?;]", sentences[batch_id])
            merged = False
            for i in range(len(tokens)):
                if merged:
                    merged = False
                    continue
                t1 = tokens[i]
                try:
                    t2 = tokens[i + 1]
                except IndexError:
                    t2 = "###"
                if (t1, t2) in self.merge_tokens:
                    if i == 0:
                        merged_embeddings = torch.stack([word_embeddings[i], word_embeddings[i + 1]]).mean(dim=0).unsqueeze(0)
                    else:
                        merged_embedding = torch.stack([word_embeddings[i], word_embeddings[i + 1]]).mean(dim=0).unsqueeze(0)
                        merged_embeddings = torch.cat([merged_embeddings, merged_embedding])
                    merged = True
                else:
                    if i == 0:
                        merged_embeddings = word_embeddings[i].unsqueeze(0)
                    else:
                        merged_embeddings = torch.cat([merged_embeddings, word_embeddings[i].unsqueeze(0)])
            word_embeddings = merged_embeddings
            #print(self.tokenizer.tokenize(sentences[batch_id]))
            word_embeddings_list.append(word_embeddings)
            # save sentence lengths
            lens.append(word_embeddings.shape[0])
        # pad tensors to max sentence length of batch
        word_embeddings_batch = pad_sequence(word_embeddings_list, batch_first=True).detach()
        # return word embeddings for each word in each sentence along with sentence lengths
        return word_embeddings_batch, lens
    
    def get_merge_tokens(self, sentence:str):
        w_list = sentence.split()
        merge_tokens = []
        for (w1, w2) in zip(w_list, w_list[1:]):
            phonemized = self.tf.get_phone_string(' '.join([w1, w2]))
            if len(phonemized.split()) < 2:
                merge_tokens.append((w1, w2))
            if len(phonemized.split()) > 2:
                print(sentence)
                print(w1)
                print(w2)
        return merge_tokens
