import json
import pickle
import random

import numpy as np
from huggingface_hub import hf_hub_download

from Utility.storage_config import MODEL_DIR
from Utility.utils import load_json_from_path


class SimilaritySolver:
    def __init__(self,
                 tree_dist=None,
                 map_dist=None,
                 asp_dict=None,
                 largest_value_map_dist=None,
                 tree_dist_path=None,
                 map_dist_path=None,
                 asp_dict_path=None,
                 iso_to_fullname=None,
                 iso_to_fullname_path=None,
                 learned_dist=None,
                 learned_dist_path=None,
                 oracle_dist=None,
                 oracle_dist_path=None,
                 force_reload=False):
        self.lang_1_to_lang_2_to_tree_dist = tree_dist
        self.lang_1_to_lang_2_to_map_dist = map_dist
        self.largest_value_map_dist = largest_value_map_dist
        self.asp_dict = asp_dict
        self.lang_1_to_lang_2_to_learned_dist = learned_dist
        self.lang_1_to_lang_2_to_oracle_dist = oracle_dist
        self.iso_to_fullname = iso_to_fullname
        iso_to_fullname_path = hf_hub_download(cache_dir=MODEL_DIR, repo_id="Flux9665/ToucanTTS", filename="iso_to_fullname.json") if not iso_to_fullname_path else iso_to_fullname_path

        if force_reload:
            tree_dist_path = hf_hub_download(cache_dir=MODEL_DIR, repo_id="Flux9665/ToucanTTS", filename="lang_1_to_lang_2_to_tree_dist.json") if not tree_dist_path else tree_dist_path
            self.lang_1_to_lang_2_to_tree_dist = load_json_from_path(tree_dist_path)
            map_dist_path = hf_hub_download(cache_dir=MODEL_DIR, repo_id="Flux9665/ToucanTTS", filename="lang_1_to_lang_2_to_map_dist.json") if not map_dist_path else map_dist_path
            self.lang_1_to_lang_2_to_map_dist = load_json_from_path(map_dist_path)
            self.largest_value_map_dist = 0.0
            for _, values in self.lang_1_to_lang_2_to_map_dist.items():
                for _, value in values.items():
                    self.largest_value_map_dist = max(self.largest_value_map_dist, value)
            learned_dist_path = hf_hub_download(cache_dir=MODEL_DIR, repo_id="Flux9665/ToucanTTS", filename="lang_1_to_lang_2_to_learned_dist.json") if not learned_dist_path else tree_dist_path
            self.lang_1_to_lang_2_to_learned_dist = load_json_from_path(learned_dist_path)
            oracle_dist_path = 'lang_1_to_lang_2_to_oracle_dist.json' if not oracle_dist_path else oracle_dist_path
            self.lang_1_to_lang_2_to_oracle_dist = load_json_from_path(oracle_dist_path)
            asp_dict_path = hf_hub_download(cache_dir=MODEL_DIR, repo_id="Flux9665/ToucanTTS", filename="asp_dict.pkl") if not asp_dict_path else asp_dict_path
            with open(asp_dict_path, "rb") as f:
                self.asp_dict = pickle.load(f)
            self.iso_to_fullname = load_json_from_path(iso_to_fullname_path)

        pop_keys = list()
        for el in self.iso_to_fullname:
            if "Sign Language" in self.iso_to_fullname[el]:
                pop_keys.append(el)
        for pop_key in pop_keys:
            self.iso_to_fullname.pop(pop_key)
        with open(iso_to_fullname_path, 'w', encoding='utf-8') as f:
            json.dump(self.iso_to_fullname, f, ensure_ascii=False, indent=4)

    def find_closest_combined_distance(self,
                                       lang,
                                       supervised_langs,
                                       combined_distance="average",
                                       k=50,
                                       individual_distances=False,
                                       verbose=False,
                                       excluded_features=[],
                                       find_furthest=False):
        """Find the k closest languages according to a combination of map distance, tree distance, and ASP distance.
        Returns a dict of dicts (`individual_distances` optional) of the format {"supervised_lang_1": 
                                                {"euclidean_distance": 5.39, "individual_distances": [<map_dist>, <tree_dist>, <asp_dist>]},
                                              "supervised_lang_2":
                                                {...}, ...}"""

        if combined_distance not in ["average", "euclidean"]:
            raise ValueError("distance needs to be `average` or `euclidean`")
        combined_dict = {}
        supervised_langs = set(supervised_langs) if isinstance(supervised_langs, list) else supervised_langs
        # avoid error with `urk`
        if "urk" in supervised_langs:
            supervised_langs.remove("urk")
        if lang in supervised_langs:
            supervised_langs.remove(lang)
        for sup_lang in supervised_langs:
            map_dist = self.get_map_distance(lang, sup_lang)
            tree_dist = self.get_tree_distance(lang, sup_lang)
            asp_score = self.get_asp(lang, sup_lang, self.asp_dict)
            # if getting one of the scores failed, ignore this language
            if None in {map_dist, tree_dist, asp_score}:
                continue

            combined_dict[sup_lang] = {}
            asp_dist = 1 - asp_score  # turn into dist since other 2 are also dists
            dist_list = []
            if "map" not in excluded_features:
                dist_list.append(map_dist)
            if "asp" not in excluded_features:
                dist_list.append(asp_dist)
            if "tree" not in excluded_features:
                dist_list.append(tree_dist)
            dist_array = np.array(dist_list)
            if combined_distance == "euclidean":
                euclidean_dist = np.sqrt(np.sum(dist_array ** 2))  # no subtraction since lang has dist [0,0,0]
                combined_dict[sup_lang]["combined_distance"] = euclidean_dist
            elif combined_distance == "average":
                avg_dist = np.mean(dist_array)
                combined_dict[sup_lang]["combined_distance"] = avg_dist

            if individual_distances:
                combined_dict[sup_lang]["individual_distances"] = [map_dist, tree_dist, asp_dist]

        results = dict(sorted(combined_dict.items(), key=lambda x: x[1]["combined_distance"], reverse=find_furthest)[:k])
        if verbose:
            sorted_by = "closest" if not find_furthest else "furthest"
            print(f"{k} {sorted_by} languages to {self.iso_to_fullname[lang]} w.r.t. the combined features are:")
            for result in results:
                try:
                    print(self.iso_to_fullname[result])
                    print(results[result])
                except KeyError:
                    print("Full Name of Language Missing")
        return results

    def find_closest(self, distance_type, lang, supervised_langs, k=50, find_furthest=False, random_seed=42, verbose=False):
        """Find the k nearest languages in terms of a given feature.
        Returns a dict {language: distance} sorted by distance."""
        distance_types = ["learned", "map", "tree", "asp", "random", "oracle"]
        if distance_type not in distance_types:
            raise ValueError(f"Invalid distance type '{distance_type}'. Expected one of {distance_types}")
        langs_to_dist = dict()
        supervised_langs = set(supervised_langs) if isinstance(supervised_langs, list) else supervised_langs
        # avoid error with `urk`
        if "urk" in supervised_langs:
            supervised_langs.remove("urk")
        if lang in supervised_langs:
            supervised_langs.remove(lang)

        if distance_type == "learned":
            for sup_lang in supervised_langs:
                dist = self.get_learned_distance(lang, sup_lang)
                if dist is not None:
                    langs_to_dist[sup_lang] = dist
        elif distance_type == "map":
            for sup_lang in supervised_langs:
                dist = self.get_map_distance(lang, sup_lang)
                if dist is not None:
                    langs_to_dist[sup_lang] = dist
        elif distance_type == "tree":
            for sup_lang in supervised_langs:
                dist = self.get_tree_distance(lang, sup_lang)
                if dist is not None:
                    langs_to_dist[sup_lang] = dist
        elif distance_type == "asp":
            for sup_lang in supervised_langs:
                asp_score = self.get_asp(lang, sup_lang, self.asp_dict)
                if asp_score is not None:
                    asp_dist = 1 - asp_score
                    langs_to_dist[sup_lang] = asp_dist
        elif distance_type == "oracle":
            for sup_lang in supervised_langs:
                dist = self.get_oracle_distance(lang, sup_lang)
                if dist is not None:
                    langs_to_dist[sup_lang] = dist
        elif distance_type == "random":
            random.seed(random_seed)
            random_langs = random.sample(supervised_langs, k)
            # create dict with all 0.5 values
            random_dict = {rand_lang: 0.5 for rand_lang in random_langs}
            return random_dict

        # sort results by distance and only keep the first k entries
        results = dict(sorted(langs_to_dist.items(), key=lambda x: x[1], reverse=find_furthest)[:k])
        if verbose:
            sorted_by = "closest" if not find_furthest else "furthest"
            print(f"{k} {sorted_by} languages to {self.iso_to_fullname[lang]} w.r.t. {distance_type} are:")
            for result in results:
                try:
                    print(self.iso_to_fullname[result])
                    print(results[result])
                except KeyError:
                    print("Full Name of Language Missing")
        return results

    def get_map_distance(self, lang_1, lang_2):
        """Returns normalized map distance between two languages.
        If no value can be retrieved, returns None."""
        try:
            dist = self.lang_1_to_lang_2_to_map_dist[lang_1][lang_2]
        except KeyError:
            try:
                dist = self.lang_1_to_lang_2_to_map_dist[lang_2][lang_1]
            except KeyError:
                return None
        dist = dist / self.largest_value_map_dist  # normalize
        return dist

    def get_tree_distance(self, lang_1, lang_2):
        """Returns normalized tree distance between two languages.
        If no value can be retrieved, returns None."""
        try:
            dist = self.lang_1_to_lang_2_to_tree_dist[lang_1][lang_2]
        except KeyError:
            try:
                dist = self.lang_1_to_lang_2_to_tree_dist[lang_2][lang_1]
            except KeyError:
                return None
        return dist

    def get_learned_distance(self, lang_1, lang_2):
        """Returns normalized learned distance between two languages.
        If no value can be retrieved, returns None."""
        try:
            dist = self.lang_1_to_lang_2_to_learned_dist[lang_1][lang_2]
        except KeyError:
            try:
                dist = self.lang_1_to_lang_2_to_learned_dist[lang_2][lang_1]
            except KeyError:
                return None
        return dist

    def get_oracle_distance(self, lang_1, lang_2):
        """Returns oracle language embedding distance (MSE) between two languages.
        If no value can be retrieved, returns None."""
        try:
            dist = self.lang_1_to_lang_2_to_oracle_dist[lang_1][lang_2]
        except KeyError:
            try:
                dist = self.lang_1_to_lang_2_to_oracle_dist[lang_2][lang_1]
            except KeyError:
                return None
        return dist

    def get_asp(self, lang_a, lang_b, path_to_dict):
        """Look up and return the ASP between lang_a and lang_b from (pre-calculated) dictionary at path_to_dict.
        Note: This is a SIMILARITY measure, NOT a distance!"""
        asp_dict = load_asp_dict(path_to_dict)
        lang_list = list(asp_dict)  # list of all languages, to get lang_b's index
        lang_b_idx = lang_list.index(lang_b)  # lang_b's index
        try:
            asp = asp_dict[lang_a][lang_b_idx]  # asp_dict's structure: {lang: numpy array of all corresponding ASPs}
        except KeyError:
            return None
        return asp


def load_asp_dict(path_to_dict):
    """If the input is already a dict, return it, else load dict from input path and return the dict."""
    if isinstance(path_to_dict, dict):
        return path_to_dict
    else:
        with open(path_to_dict, 'rb') as dictfile:
            asp_dict = pickle.load(dictfile)
        return asp_dict
