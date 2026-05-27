"""Eliza - a pattern-matching conversational agent for testing tuochat.

Classic ELIZA-style responses without mental-health/therapy framing.
Covers everyday conversation: greetings, opinions, hobbies, work, weather,
food, travel, sports, idle chat, etc.

No third-party dependencies.
"""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Callable, Iterator
from typing import Any

#
# Reflection table: flip pronouns when echoing the user back.
#
REFLECTIONS: dict[str, str] = {
    r"\bI\b": "you",
    r"\bme\b": "you",
    r"\bmy\b": "your",
    r"\bmine\b": "yours",
    r"\bmyself\b": "yourself",
    r"\bI'm\b": "you're",
    r"\bI've\b": "you've",
    r"\bI'll\b": "you'll",
    r"\bI'd\b": "you'd",
    r"\bI was\b": "you were",
    r"\bam\b": "are",
    r"\bwas\b": "were",
    r"\byou\b": "I",
    r"\byour\b": "my",
    r"\byours\b": "mine",
    r"\byourself\b": "myself",
    r"\byou're\b": "I'm",
    r"\byou've\b": "I've",
    r"\byou'll\b": "I'll",
    r"\byou'd\b": "I'd",
    r"\byou were\b": "I was",
    r"\bare\b": "am",
    r"\bwere\b": "was",
}


def reflect(text: str) -> str:
    """Mirror pronouns so echoed phrases read naturally."""
    # Use a single regex match to avoid double-replacing (e.g., I -> you -> I)
    pattern = re.compile("|".join(REFLECTIONS.keys()), flags=re.IGNORECASE)

    # Simple mapping without regex for the actual lookup to be fast
    lookup = {k.replace(r"\b", "").lower(): v for k, v in REFLECTIONS.items()}

    def replace(match: re.Match[str]) -> str:
        word = match.group(0)
        return lookup.get(word.lower(), word)

    return pattern.sub(replace, text)


#
# Pattern rules.
# Each rule: (compiled-regex, [response-templates])
# Templates may contain {0}, {1} ... for captured groups (reflected).
#
RAW_RULES: list[tuple[str, list[str]]] = [
    # ---- greetings ----
    (
        r"^(?:hi|hey|hello|howdy|sup|what'?s up|yo)[!.]*\s*$",
        [
            "Hey there! How's it going?",
            "Hi! What's on your mind today?",
            "Hello! Nice to hear from you. What are you up to?",
            "Hey! How are you doing?",
        ],
    ),
    # ---- how are you ----
    (
        r"how are you|how('s| is) it going|how do you do",
        [
            "I'm doing well, thanks for asking! What about you?",
            "Pretty good! How are things on your end?",
            "All good here. What's new with you?",
        ],
    ),
    # ---- I am (feeling/state) ----
    (
        r"i(?:'m| am) ((?:very |really |so |quite |pretty )?(?:\w+ ?){1,4})",
        [
            "Why do you say you're {0}?",
            "How long have you been {0}?",
            "What do you think makes you feel {0}?",
            "Tell me more about being {0}.",
            "Interesting — what does being {0} feel like for you?",
        ],
    ),
    # ---- I feel ----
    (
        r"i (?:feel|felt) ((?:\w+ ?){1,5})",
        [
            "What makes you feel {0}?",
            "Do you often feel {0}?",
            "Tell me more about feeling {0}.",
            "When did you start feeling {0}?",
        ],
    ),
    # ---- I want / I need ----
    (
        r"i (?:want|would like|wish|need) ((?:\w+ ?){1,8})",
        [
            "Why do you want {0}?",
            "What would it mean to you if you had {0}?",
            "How long have you wanted {0}?",
            "What would you do if you got {0}?",
        ],
    ),
    # ---- I think / I believe ----
    (
        r"i (?:think|believe|reckon|suppose|guess) ((?:\w+ ?){1,12})",
        [
            "Why do you think {0}?",
            "Do you really believe {0}?",
            "What makes you say {0}?",
            "What would change if {0} turned out not to be true?",
        ],
    ),
    # ---- I like / I love ----
    (
        r"i (?:like|love|enjoy|adore|prefer) ((?:\w+ ?){1,8})",
        [
            "What do you like most about {0}?",
            "How long have you enjoyed {0}?",
            "Would you recommend {0} to a friend?",
            "What got you into {0}?",
        ],
    ),
    # ---- I hate / I dislike ----
    (
        r"i (?:hate|dislike|can't stand|detest|loathe) ((?:\w+ ?){1,8})",
        [
            "Why don't you like {0}?",
            "Has it always bothered you?",
            "What would have to change about {0} for you to like it?",
            "Strong feelings! Tell me more.",
        ],
    ),
    # ---- food / eating ----
    (
        r"(?:eat|ate|food|meal|dinner|lunch|breakfast|snack|cook|restaurant|pizza|burger|sushi|pasta)",
        [
            "Are you a big foodie?",
            "What's your favourite cuisine?",
            "Do you enjoy cooking at home or eating out more?",
            "What's the best meal you've had recently?",
            "Any go-to comfort food?",
        ],
    ),
    # ---- weather ----
    (
        r"(?:weather|rain|sunny|snow|cold|hot|warm|humid|wind|forecast|temperature|degrees)",
        [
            "What's the weather like where you are?",
            "Do you prefer warm or cold weather?",
            "Has the weather been affecting your mood lately?",
            "I hear the forecast has been unpredictable. What's it like for you?",
        ],
    ),
    # ---- work / job ----
    (
        r"(?:work|job|office|boss|colleague|coworker|meeting|deadline|project|career|salary|promotion|interview)",
        [
            "How do you feel about your work these days?",
            "Is work keeping you busy?",
            "What do you find most interesting about your job?",
            "Do you get along well with the people you work with?",
            "Any big projects on your plate right now?",
        ],
    ),
    # ---- sports ----
    (
        r"(?:sport|football|soccer|basketball|tennis|cricket|baseball|rugby|gym|run|running|cycling|swim|hiking|yoga|exercise|fitness)",
        [
            "Are you into sports much?",
            "Do you play, or more of a spectator?",
            "What got you interested in that?",
            "How often do you get to do that?",
            "Any favourite teams or athletes?",
        ],
    ),
    # ---- music ----
    (
        r"(?:music|song|band|concert|album|playlist|listen|spotify|guitar|piano|sing|singer|artist)",
        [
            "What kind of music are you into?",
            "Any artists you've been listening to a lot lately?",
            "Do you play any instruments?",
            "What's the last gig or concert you went to?",
            "Music really sets the mood, doesn't it?",
        ],
    ),
    # ---- movies / TV ----
    (
        r"(?:movie|film|tv|television|show|series|netflix|watch|episode|cinema|stream|documentary|director|actor)",
        [
            "What have you been watching lately?",
            "Any film or show you'd strongly recommend?",
            "Do you prefer movies or series?",
            "What genre do you tend to go for?",
            "Who's your favourite director or actor?",
        ],
    ),
    # ---- books / reading ----
    (
        r"(?:book|read|reading|novel|author|library|chapter|fiction|nonfiction|genre|kindle|e-book)",
        [
            "What have you been reading lately?",
            "Do you prefer fiction or non-fiction?",
            "Any book you'd recommend without hesitation?",
            "How much time do you spend reading?",
            "Favourite author?",
        ],
    ),
    # ---- travel ----
    (
        r"(?:travel|trip|vacation|holiday|flight|hotel|country|city|abroad|visit|tour|backpack|passport|tourist)",
        [
            "Do you travel much?",
            "What's the best place you've visited?",
            "Anywhere on your bucket list?",
            "Do you prefer city breaks or nature trips?",
            "What do you enjoy most about travelling?",
        ],
    ),
    # ---- technology / computers ----
    (
        r"(?:computer|laptop|phone|app|software|code|program|internet|tech|ai|robot|gadget|device)",
        [
            "Are you into tech?",
            "What kind of tech do you work with day-to-day?",
            "Do you keep up with new gadgets and software?",
            "What's the most useful bit of tech in your life right now?",
        ],
    ),
    # ---- family / friends ----
    (
        r"(?:family|friend|mum|mom|dad|father|mother|sister|brother|sibling|parent|child|kid|son|daughter|partner|spouse|wife|husband)",
        [
            "Are you close with your family?",
            "How are things with the people close to you?",
            "How long have you known them?",
            "What do you enjoy doing together?",
        ],
    ),
    # ---- pets / animals ----
    (
        r"(?:pet|dog|cat|bird|fish|hamster|rabbit|animal|puppy|kitten)",
        [
            "Do you have any pets?",
            "What kind of pet do you have?",
            "I've heard pets can be great company. What's yours like?",
            "Animals are great. What do you enjoy most about them?",
        ],
    ),
    # ---- hobbies ----
    (
        r"(?:hobby|hobbies|pastime|free time|spare time|weekend|fun|creative|draw|paint|craft|game|gaming|knit|garden|photography)",
        [
            "What do you like to do in your spare time?",
            "How did you get into that hobby?",
            "How much time do you get to spend on it?",
            "Do you prefer hobbies you do alone or with others?",
        ],
    ),
    # ---- yes ----
    (
        r"^(?:yes|yeah|yep|yup|sure|absolutely|definitely|of course|right|exactly|indeed|totally|certainly)[!.]*\s*$",
        [
            "Great! Tell me more.",
            "Glad to hear it. What else is on your mind?",
            "Sounds good. What would you like to talk about?",
            "Alright! Anything else you'd like to share?",
        ],
    ),
    # ---- no ----
    (
        r"^(?:no|nope|nah|not really|not at all|never)[!.]*\s*$",
        [
            "Fair enough! What would you rather talk about?",
            "That's okay. Anything else on your mind?",
            "Alright, I understand. What else is going on?",
        ],
    ),
    # ---- thank you ----
    (
        r"(?:thank(?:s| you)|cheers|ta\b|appreciate it|much appreciated)",
        [
            "You're welcome! Is there anything else you'd like to chat about?",
            "Happy to help! What else is on your mind?",
            "No problem at all!",
            "Anytime! What else would you like to talk about?",
        ],
    ),
    # ---- sorry / apology ----
    (
        r"(?:sorry|apologise|apologies|my bad|forgive me|excuse me)",
        [
            "No worries at all!",
            "Don't worry about it.",
            "All good!",
            "No need to apologise.",
        ],
    ),
    # ---- goodbye ----
    (
        r"(?:bye|goodbye|see you|see ya|cya|ttyl|later|take care|gotta go|got to go|farewell)",
        [
            "Goodbye! It was nice chatting.",
            "Take care! Feel free to come back any time.",
            "See you later! Have a great day.",
            "Bye! Looking forward to chatting again.",
        ],
    ),
    # ---- what do you think ----
    (
        r"what do you think(?: about)?(.*)?",
        [
            "What do *you* think about {0}?",
            "That's an interesting question about {0}. What's your take?",
            "I'd love to hear your thoughts on {0} first.",
            "Hmm, what led you to wondering about {0}?",
        ],
    ),
    # ---- questions directed at Eliza ----
    (
        r"(?:do you|are you|can you|have you|will you)(.*)?",
        [
            "Let's keep the focus on you — tell me more.",
            "That's an interesting question. What made you think of that?",
            "Why do you ask?",
            "What would it mean if I did {0}?",
        ],
    ),
    # ---- why questions ----
    (
        r"^why (.*)",
        [
            "What makes you curious about why {0}?",
            "Good question — why do *you* think {0}?",
            "Does the reason really matter to you?",
            "What would the answer change for you?",
        ],
    ),
    # ---- how questions ----
    (
        r"^how (.*)",
        [
            "How do *you* think about {0}?",
            "What have you tried so far?",
            "What would be a good outcome for you?",
            "Tell me more about what you're trying to figure out.",
        ],
    ),
    # ---- what questions ----
    (
        r"^what (.*)",
        [
            "What do *you* think about {0}?",
            "Why are you asking about {0}?",
            "What would you do with the answer?",
            "Good question! What's your gut feeling about {0}?",
        ],
    ),
    # ---- because / reason ----
    (
        r"because (.*)",
        [
            "Is {0} the main reason?",
            "Does that reason fully explain it, or is there more to it?",
            "What else comes to mind?",
            "How does {0} make you feel?",
        ],
    ),
    # ---- always / never ----
    (
        r"(?:always|never)(.*)",
        [
            "Can you think of a specific example?",
            "Really, always? Or does it just feel that way sometimes?",
            "What leads you to say that?",
            "That sounds pretty definitive — what's behind it?",
        ],
    ),
    # ---- everyone / nobody ----
    (
        r"(?:everyone|everybody|nobody|no one|people always|people never)(.*)",
        [
            "Is that true of everyone, or just some people?",
            "What makes you feel that way about people?",
            "Interesting take — can you give me an example?",
            "Do you really think all people are like that?",
        ],
    ),
    # ---- I can't / I don't ----
    (
        r"i (?:can't|cannot|don't|won't|couldn't|wouldn't) (.*)",
        [
            "What stops you from {0}?",
            "Have you ever been able to {0}?",
            "What would need to change for you to {0}?",
            "What would it be like if you could {0}?",
        ],
    ),
    # ---- I did / I've done ----
    (
        r"i (?:did|made|built|wrote|finished|completed|achieved|tried) (.*)",
        [
            "How did that go?",
            "Are you happy with how {0} turned out?",
            "What did you learn from doing that?",
            "That sounds interesting — tell me more.",
        ],
    ),
    # ---- short affirmations / filler ----
    (
        r"^(?:ok|okay|alright|right|cool|great|nice|interesting|hm+|hmm+|ah+|oh+)[.!]*\s*$",
        [
            "What's on your mind?",
            "Tell me more.",
            "Go on.",
            "What would you like to talk about?",
            "I'm listening.",
        ],
    ),
    # ---- what's your name ----
    (
        r"(?:what(?:'s| is) your name|who are you|what are you)",
        [
            "I'm Eliza, a simple conversational program. Nothing too clever! What's your name?",
            "People call me Eliza. And you?",
            "I'm Eliza — happy to chat. What shall I call you?",
        ],
    ),
    # ---- my name is ----
    (
        r"(?:my name is|i(?:'m| am) called|call me|i go by) (\w+)",
        [
            "Nice to meet you, {0}! What would you like to talk about?",
            "Hello, {0}! What's been going on with you?",
            "{0} — that's a nice name. What's on your mind?",
        ],
    ),
]

# Compile all rules once at module load.
RULES: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(pattern, re.IGNORECASE), responses) for pattern, responses in RAW_RULES
]

#
# Fallback responses when nothing matches.
#
FALLBACKS: list[str] = [
    "Tell me more.",
    "Go on.",
    "I see. Can you elaborate?",
    "That's interesting — say more.",
    "What else comes to mind?",
    "How does that make you feel?",
    "And what do you make of that?",
    "Mm-hmm. What else?",
    "Why do you say that?",
    "Can you give me an example?",
    "Interesting. What do you think that means?",
    "I'm curious — what happened next?",
    "What led you to thinking about that?",
    "Is there anything else you'd like to add?",
]


class ElizaProvider:
    """Local pattern-matching chat provider.

    Requires no network access and no configuration beyond instantiation.
    Intended for testing the tuochat UI without latency or API cost.
    """

    def __init__(self) -> None:
        self.last_fallback: int = -1
        # Track last used template per rule to avoid immediate repeats.
        self.rule_last_used: dict[int, int] = {}

    # ------------------------------------------------------------------
    # Public interface (matches DuoProvider.chat signature)
    # ------------------------------------------------------------------

    def chat(
        self,
        question: str,
        resource_id: str | None = None,  # noqa: ARG002
        streaming: bool = True,
        cancel: Callable[[], bool] | None = None,
        additional_context: list[dict[str, Any]] | None = None,
    ) -> Iterator[str]:
        """Yield Eliza's response to *question*.

        If streaming is True, yields word-by-word with a small delay to
        simulate a real streaming model.  Otherwise yields the full response
        as a single string.
        """
        _ = resource_id, cancel, additional_context
        response = self.respond(question.strip())

        if streaming:
            yield from self.stream_words(response)
        else:
            yield response

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def respond(self, text: str) -> str:
        for idx, (pattern, templates) in enumerate(RULES):
            m = pattern.search(text)
            if m:
                # Pick a template we haven't used the last time for this rule.
                last = self.rule_last_used.get(idx, -1)
                available = [i for i in range(len(templates)) if i != last]
                choice = secrets.choice(available if available else list(range(len(templates))))
                self.rule_last_used[idx] = choice
                template = templates[choice]

                # Fill in captured groups (reflected).
                groups = [reflect(g.strip()) if g else "" for g in m.groups()]
                try:
                    return template.format(*groups)
                except (IndexError, KeyError):
                    return template

        return self.fallback()

    def fallback(self) -> str:
        available = [i for i in range(len(FALLBACKS)) if i != self.last_fallback]
        choice = secrets.choice(available if available else list(range(len(FALLBACKS))))
        self.last_fallback = choice
        return FALLBACKS[choice]

    @staticmethod
    def stream_words(text: str) -> Iterator[str]:
        """Yield words one at a time with a small inter-word delay."""
        words = text.split()
        for i, word in enumerate(words):
            chunk = word if i == 0 else " " + word
            yield chunk
            time.sleep(0.04)
