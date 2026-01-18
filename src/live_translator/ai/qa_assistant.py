"""
QA Assistant module for AI-powered learning help
"""
import re
import threading
from live_translator.ai.api_client import APIClient

# Question detection patterns
QUESTION_PATTERNS = [
    # English question words
    r'\b(what|who|where|when|why|how|which|whose|whom)\b[^.!]*\?',
    r'\b(can|could|would|will|do|does|did|is|are|was|were|have|has|had)\b[^.!]*\?',
    r'\b(should|shall|may|might|must)\b[^.!]*\?',
    # Direct questions ending with ?
    r'[^.!]+\?',
    # Common question phrases
    r'\b(tell me|explain|describe|what about|how about)\b[^.!]*[.?]?',
]

# Prompt templates
QA_PROMPT = """Based on the following context from a live translation session:

{context}

Question: {question}

Provide a clear, helpful answer. If you cannot find a direct answer in the context, say "I cannot find a direct answer" and explain what information would be needed.

Answer:"""

SUMMARY_PROMPT = """Summarize the following content from a live translation session.
Highlight key points, important terms, and main ideas.

Content:
{context}

Summary:"""

LEARNING_PROMPT = """Based on this content from a live translation session:

{context}

{question}

Provide educational help including:
- Definitions of key terms mentioned
- Cultural or contextual information
- Related vocabulary and phrases
- Tips for better understanding

Response:"""

TIPS_PROMPT = """The user asked: "{question}"

Based on available context, I cannot provide a complete answer. Please provide:

1. Key terms the user should research
2. Clarifying questions that might help narrow down what they're looking for
3. Any partial information that might be relevant
4. Suggested next steps or resources

Context summary: {context_summary}

Tips and suggestions:"""


class QAAssistant:
    def __init__(self, provider="ollama", model="mistral:7b",
                 source_language="English", target_language="Russian"):
        """
        Initialize QA Assistant.

        Args:
            provider: AI provider (ollama, openai, anthropic)
            model: Model name
            source_language: Original text language
            target_language: User's preferred language for responses
        """
        self.provider = provider
        self.model = model
        self.source_language = source_language
        self.target_language = target_language

        # Use shared API client with timeout
        self._client = APIClient(provider=provider, model=model, timeout=30)

        # Prompt templates
        self.qa_prompt = QA_PROMPT
        self.summary_prompt = SUMMARY_PROMPT
        self.learning_prompt = LEARNING_PROMPT
        self.tips_prompt = TIPS_PROMPT

    def set_settings(self, provider=None, model=None, source_language=None,
                     target_language=None, qa_prompt=None, summary_prompt=None,
                     learning_prompt=None):
        """Update assistant settings."""
        if provider:
            self.provider = provider
        if model:
            self.model = model
        if source_language:
            self.source_language = source_language
        if target_language:
            self.target_language = target_language
        if qa_prompt:
            self.qa_prompt = qa_prompt
        if summary_prompt:
            self.summary_prompt = summary_prompt
        if learning_prompt:
            self.learning_prompt = learning_prompt
        # Update API client settings
        self._client.set_settings(provider=provider, model=model)

    def detect_questions(self, text):
        """
        Detect questions in the transcribed text.

        Args:
            text: Transcribed text to analyze

        Returns:
            list of detected questions
        """
        if not text:
            return []

        questions = []
        text_lower = text.lower()

        # First, find all sentences ending with ?
        question_mark_sentences = re.findall(r'[^.!?]*\?', text, re.IGNORECASE)
        for q in question_mark_sentences:
            q = q.strip()
            if q and len(q) > 5:  # Filter out very short matches
                questions.append(q)

        # If no question marks, look for question patterns
        if not questions:
            for pattern in QUESTION_PATTERNS[:-1]:  # Skip the generic ? pattern
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    if isinstance(match, tuple):
                        # Get the full match context
                        continue
                    match = match.strip()
                    if match and len(match) > 10 and match not in questions:
                        questions.append(match)

        # Remove duplicates while preserving order
        seen = set()
        unique_questions = []
        for q in questions:
            q_lower = q.lower().strip()
            if q_lower not in seen:
                seen.add(q_lower)
                unique_questions.append(q.strip())

        return unique_questions

    def process_detected_question(self, question, context):
        """
        Process a detected question from transcription.

        Args:
            question: The detected question
            context: Recent transcription context for answering

        Returns:
            dict with question, original_response, translated_response
        """
        result = self.ask(context, question, mode="qa")
        result["detected_question"] = question
        return result

    def ask(self, context, question="", mode="qa"):
        """
        Main entry point for AI assistance.

        Args:
            context: Recent transcription/translation text
            question: User's question (optional for summary mode)
            mode: "qa", "summary", or "learning"

        Returns:
            dict with:
                - success: bool
                - original_response: str (response in source language)
                - translated_response: str (response in target language)
                - is_tips: bool (True if fallback tips were generated)
        """
        if not context or not context.strip():
            return {
                "success": False,
                "original_response": "No context available. Please wait for some transcription.",
                "translated_response": "Нет контекста. Пожалуйста, дождитесь транскрипции.",
                "is_tips": False
            }

        try:
            # Build prompt based on mode
            if mode == "summary":
                prompt = self.summary_prompt.format(context=context)
            elif mode == "learning":
                prompt = self.learning_prompt.format(
                    context=context,
                    question=question or "Provide general learning help for this content."
                )
            else:  # qa mode
                if not question:
                    return {
                        "success": False,
                        "original_response": "Please enter a question.",
                        "translated_response": "Пожалуйста, введите вопрос.",
                        "is_tips": False
                    }
                prompt = self.qa_prompt.format(context=context, question=question)

            # Generate response
            response = self._generate_response(prompt)

            if not response:
                # Generate tips as fallback
                return self._generate_tips_response(context, question)

            # Check if response indicates no answer found
            no_answer_indicators = [
                "cannot find", "don't have enough", "no information",
                "not mentioned", "unable to answer", "cannot determine"
            ]
            if any(indicator in response.lower() for indicator in no_answer_indicators):
                tips_result = self._generate_tips_response(context, question)
                # Combine original response with tips
                tips_result["original_response"] = response + "\n\n" + tips_result["original_response"]
                return tips_result

            # Translate response to target language
            translated = self._translate_response(response)

            return {
                "success": True,
                "original_response": response,
                "translated_response": translated or response,
                "is_tips": False
            }

        except Exception as e:
            print(f"QA Assistant error: {e}")
            return {
                "success": False,
                "original_response": f"Error generating response: {e}",
                "translated_response": f"Ошибка генерации ответа: {e}",
                "is_tips": False
            }

    def _generate_response(self, prompt):
        """Generate response using configured provider."""
        try:
            return self._client.generate(prompt)
        except Exception as e:
            print(f"Response generation error: {e}")
            return None

    def _translate_response(self, text):
        """Translate AI response to target language."""
        if not text:
            return None

        translate_prompt = f"""Translate the following text to {self.target_language}.
Output ONLY the translation, nothing else:

{text}"""

        try:
            return self._generate_response(translate_prompt)
        except Exception as e:
            print(f"Translation error: {e}")
            return None

    def _generate_tips_response(self, context, question):
        """Generate tips and suggestions when direct answer not possible."""
        # Create a brief context summary
        context_lines = context.split('\n')
        context_summary = ' '.join(context_lines[:5])[:500] + "..."

        prompt = self.tips_prompt.format(
            question=question or "general understanding",
            context_summary=context_summary
        )

        tips = self._generate_response(prompt)

        if not tips:
            tips = """Unable to generate a response. Suggestions:
1. Try rephrasing your question
2. Wait for more context from the transcription
3. Ask a more specific question about the content"""

        translated_tips = self._translate_response(tips)

        return {
            "success": True,
            "original_response": tips,
            "translated_response": translated_tips or tips,
            "is_tips": True
        }


# Global instance with thread-safe initialization
_qa_assistant = None
_qa_assistant_lock = threading.Lock()


def get_qa_assistant():
    global _qa_assistant
    if _qa_assistant is None:
        with _qa_assistant_lock:
            # Double-check locking pattern
            if _qa_assistant is None:
                _qa_assistant = QAAssistant()
    return _qa_assistant


if __name__ == "__main__":
    # Test QA Assistant
    assistant = QAAssistant()

    test_context = """
Original:
Hello everyone, today we're going to discuss machine learning algorithms.
The first topic is neural networks and how they work.

Translation:
Привет всем, сегодня мы обсудим алгоритмы машинного обучения.
Первая тема - нейронные сети и как они работают.
"""

    # Test Q&A
    print("Testing Q&A mode:")
    result = assistant.ask(test_context, "What is the first topic?", mode="qa")
    print(f"Success: {result['success']}")
    print(f"Original: {result['original_response'][:200]}...")
    print(f"Translated: {result['translated_response'][:200]}...")
    print("-" * 50)

    # Test Summary
    print("\nTesting Summary mode:")
    result = assistant.ask(test_context, mode="summary")
    print(f"Success: {result['success']}")
    print(f"Original: {result['original_response'][:200]}...")
