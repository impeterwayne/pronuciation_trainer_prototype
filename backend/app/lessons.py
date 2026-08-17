"""Practice content.

Chosen to exercise the contrasts an L2 English speaker actually loses, and to be
easy to eyeball while tuning the scorer: minimal pairs are the cleanest test of a
pronunciation scorer, because the two members differ by exactly one phone. If you
say "sheep" and the app scores "ship" highly, your thresholds are too loose.
"""

from __future__ import annotations

from typing import Any

LESSONS: list[dict[str, Any]] = [
    {
        "id": "th",
        "title": "The 'th' sounds",
        "focus": "θ / ð",
        "level": "core",
        "why": "Neither sound exists in most languages; learners swap in /s/, /t/, /d/ or /z/.",
        "items": ["think", "three", "thin", "month", "birthday",
                  "this", "they", "mother", "breathe", "together"],
        "minimal_pairs": [["think", "sink"], ["three", "tree"], ["thin", "tin"],
                          ["they", "day"], ["breathe", "breeze"]],
        "sentences": ["I think this is the third one.",
                      "Their mother breathes through her mouth."],
    },
    {
        "id": "r-l",
        "title": "/r/ versus /l/",
        "focus": "ɹ / l",
        "level": "core",
        "why": "Two very different tongue positions that many learners merge.",
        "items": ["right", "light", "road", "load", "correct", "collect",
                  "problem", "really", "world", "girl"],
        "minimal_pairs": [["rice", "lice"], ["right", "light"], ["road", "load"],
                          ["pray", "play"], ["fry", "fly"]],
        "sentences": ["Really long roads are rarely level.",
                      "Please collect the correct file."],
    },
    {
        "id": "v-w-b",
        "title": "/v/, /w/ and /b/",
        "focus": "v / w / b",
        "level": "core",
        "why": "/v/ needs teeth on lip; substituting /w/ or /b/ changes the word.",
        "items": ["very", "value", "vote", "video", "invest",
                  "west", "water", "would", "beautiful", "believe"],
        "minimal_pairs": [["very", "berry"], ["vest", "west"], ["van", "ban"],
                          ["vine", "wine"], ["curve", "curb"]],
        "sentences": ["Every visitor was very welcome.",
                      "We believe the video is valuable."],
    },
    {
        "id": "long-short-vowels",
        "title": "Long versus short vowels",
        "focus": "iː / ɪ, uː / ʊ",
        "level": "core",
        "why": "English contrasts vowel length AND quality; shortening /iː/ gives a different word.",
        "items": ["sheep", "ship", "beat", "bit", "leave", "live",
                  "fool", "full", "pool", "pull"],
        "minimal_pairs": [["sheep", "ship"], ["beat", "bit"], ["leave", "live"],
                          ["feel", "fill"], ["fool", "full"]],
        "sentences": ["These cheap sheep are still asleep.",
                      "He will fill the full pool."],
    },
    {
        "id": "final-consonants",
        "title": "Final consonants and endings",
        "focus": "-s, -ed, -th, clusters",
        "level": "core",
        "why": "Dropping the final consonant erases tense, number and meaning.",
        "items": ["cats", "dogs", "horses", "asked", "worked", "wanted",
                  "sixth", "texts", "clothes", "months"],
        "minimal_pairs": [["card", "car"], ["hold", "whole"], ["past", "pass"],
                          ["find", "fine"], ["build", "bill"]],
        "sentences": ["She asked for the texts last month.",
                      "The kids washed their clothes."],
    },
    {
        "id": "clusters",
        "title": "Consonant clusters",
        "focus": "str-, spl-, -lfθs",
        "level": "advanced",
        "why": "Learners tend to insert a vowel between the consonants.",
        "items": ["street", "strength", "splash", "screen", "square",
                  "twelfths", "world", "crisps", "glimpse", "sixths"],
        "minimal_pairs": [["street", "seat"], ["splash", "slash"],
                          ["screen", "green"]],
        "sentences": ["The strong student crossed the street.",
                      "Twelve twelfths equal one whole."],
    },
    {
        "id": "stress",
        "title": "Word stress",
        "focus": "ˈ placement",
        "level": "advanced",
        "why": "Stress moves with part of speech; wrong stress is heard as a wrong word.",
        "items": ["present", "record", "object", "contrast", "increase",
                  "photograph", "photography", "photographic", "comfortable", "vegetable"],
        "minimal_pairs": [["desert", "dessert"], ["insight", "incite"]],
        "sentences": ["I will present the present tomorrow.",
                      "Photography is not photographic."],
    },
    {
        "id": "everyday",
        "title": "Everyday sentences",
        "focus": "connected speech",
        "level": "practice",
        "why": "Real rhythm, weak forms and linking - the hardest part of fluency.",
        "items": ["hello", "thank you", "excuse me", "how are you", "nice to meet you"],
        "minimal_pairs": [],
        "sentences": [
            "Could you tell me where the station is?",
            "I would like a cup of coffee, please.",
            "What time does the meeting start tomorrow?",
            "She has been working here for three years.",
            "I am not sure whether that is the right answer.",
        ],
    },
    {
        "id": "twisters",
        "title": "Tongue twisters",
        "focus": "everything at once",
        "level": "challenge",
        "why": "Stress test for the scorer as much as for the learner.",
        "items": [],
        "minimal_pairs": [],
        "sentences": [
            "She sells seashells by the seashore.",
            "Red lorry, yellow lorry.",
            "The thirty-three thieves thought they thrilled the throne.",
            "Peter Piper picked a peck of pickled peppers.",
        ],
    },
]

_BY_ID = {lesson["id"]: lesson for lesson in LESSONS}


def all_lessons() -> list[dict[str, Any]]:
    return LESSONS


def get_lesson(lesson_id: str) -> dict[str, Any] | None:
    return _BY_ID.get(lesson_id)


def all_prompts() -> list[str]:
    """Flat list of every practisable string - handy for smoke tests."""
    out: list[str] = []
    for lesson in LESSONS:
        out.extend(lesson["items"])
        out.extend(lesson["sentences"])
        out.extend(w for pair in lesson["minimal_pairs"] for w in pair)
    return sorted(set(out))
