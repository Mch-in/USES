"""Service for working with the ChatGPT API."""
import os
import json
import logging
import re
from typing import Optional, Dict, Any, List, Callable, Tuple, TYPE_CHECKING
from django.conf import settings

if TYPE_CHECKING:
    from openai import OpenAI

logger = logging.getLogger(__name__)

# Max assistant turns that include tool_calls before we stop (each turn may batch multiple tools).
MAX_TOOL_AGENT_ROUNDS = getattr(settings, "AI_MAX_TOOL_AGENT_ROUNDS", 5)

# (tool_messages for API, optional table payload for UI)
AnalysisToolExecutor = Callable[
    [List[Dict[str, Any]]], Tuple[List[Dict[str, str]], Optional[Dict[str, Any]]]
]

MAX_HISTORY_MESSAGES = getattr(settings, "AI_MAX_HISTORY_MESSAGES", 6)


class LLMService:
    """Service for working with the ChatGPT API."""

    client: Optional["OpenAI"] = None

    def __init__(self):
        self.client = None
        self.model_type = getattr(settings, 'GPT_MODEL_TYPE', 'openai')
        self.api_key = getattr(settings, 'OPENAI_API_KEY', '')
        self.model_name = getattr(settings, 'OPENAI_MODEL', 'gpt-4o')
        self.api_base = getattr(settings, 'OPENAI_API_BASE', None)  # For custom API endpoints
        self._initialized = False
        
        # Models that require max_completion_tokens instead of max_tokens
        self.models_using_max_completion_tokens = ['o1', 'o1-preview', 'o1-mini', 'o1-mini-preview']
        
    def _detect_language(self, text: str) -> str:
        """
        Detect user's language for response selection.

        Returns one of: 'ru', 'uk', 'en'.
        This is a lightweight heuristic (no external deps) and is intentionally conservative:
        - If Ukrainian-specific letters are present -> 'uk'
        - Else if Cyrillic dominates -> 'ru'
        - Else -> 'en'
        """
        t = (text or "").strip()
        if not t:
            return "ru"

        # Ukrainian-specific letters (upper+lower)
        if re.search(r"[іїєґІЇЄҐ]", t):
            return "uk"

        cyr = len(re.findall(r"[А-Яа-яЁё]", t))
        lat = len(re.findall(r"[A-Za-z]", t))

        if cyr > lat:
            return "ru"
        return "en"

    def _i18n(self, lang: str) -> Dict[str, str]:
        """Small UI text dictionary for prompts (ru/uk/en)."""
        lang = lang if lang in ("ru", "uk", "en") else "ru"
        return {
            "ru": {
                "headers": "Заголовки",
                "data": "Данные",
                "total_rows_fmt": "... (всего {n} строк)",
                "user_question": "Исходный вопрос пользователя",
                "section_key_findings": "Ключевые выводы",
                "section_trend_analysis": "Анализ тенденций",
                "section_problem_areas": "Проблемные области",
                "section_recommendations": "Рекомендации",
                "conclusions": "Выводы и рекомендации",
            },
            "uk": {
                "headers": "Заголовки",
                "data": "Дані",
                "total_rows_fmt": "... (усього {n} рядків)",
                "user_question": "Початкове питання користувача",
                "section_key_findings": "Ключові висновки",
                "section_trend_analysis": "Аналіз тенденцій",
                "section_problem_areas": "Проблемні області",
                "section_recommendations": "Рекомендації",
                "conclusions": "Висновки та рекомендації",
            },
            "en": {
                "headers": "Headers",
                "data": "Data",
                "total_rows_fmt": "... ({n} total rows)",
                "user_question": "User's original question",
                "section_key_findings": "Key findings",
                "section_trend_analysis": "Trend analysis",
                "section_problem_areas": "Problem areas",
                "section_recommendations": "Recommendations",
                "conclusions": "Conclusions and recommendations",
            },
        }[lang]

    def _language_policy_block(self) -> str:
        return """═══════════════════════════════════════════════════════════════
CRITICAL — LANGUAGE POLICY
═══════════════════════════════════════════════════════════════
- The user may write in Russian (ru), Ukrainian (uk), or English (en).
- Detect the language of the user's question and answer in the SAME language.
- If the input is mixed, use the dominant language.
- Do not translate the user's question unless they explicitly ask.
- Keep names, IDs, numbers, dates, currencies, and proper nouns exactly as in the data.
═══════════════════════════════════════════════════════════════
"""

    def _no_placeholder_numbers_block(self) -> str:
        return """═══════════════════════════════════════════════════════════════
CRITICAL — REAL FIGURES ONLY (LETTER PLACEHOLDERS ARE INVALID OUTPUT)
═══════════════════════════════════════════════════════════════
- NEVER write Latin letters as substitutes for numbers or unnamed managers:
  forbidden patterns include "составил X", "достигло Y", "средняя A", "максимум C",
  "менеджер Z", "X vs Y", "равно N" when X/Y/A/C/Z/N stand for missing data.
- ALWAYS paste the actual values from your query/`result` or from the PREVIOUS DIALOG table
  (full amounts, counts, averages, max deals — digits and decimal separators as in the data).
- If you do not have a figure yet: do NOT write interpretive prose with placeholders.
  First output ```python ... ``` that builds `result`, then write prose using ONLY those numbers.
- For named people use real manager names from the database; never "менеджер Z".
═══════════════════════════════════════════════════════════════
"""

    def initialize(self):
        """Initialize the OpenAI client."""
        if self._initialized:
            return True
        
        if not self.api_key:
            logger.warning("OPENAI_API_KEY is not set. The model will not be loaded.")
            return False
        
        try:
            from openai import OpenAI
            
            if self.api_base:
                self.client = OpenAI(api_key=self.api_key, base_url=self.api_base)
            else:
                self.client = OpenAI(api_key=self.api_key)
            self._initialized = True
            logger.info(f"ChatGPT client initialized successfully. Model: {self.model_name}")
            return True
        except ImportError:
            logger.error("openai is not installed. Please install: pip install openai")
            raise
        except Exception as e:
            logger.exception(f"Error while initializing OpenAI client: {e}")
            return False
    
    def generate(self, prompt: str, max_tokens: int = 512, temperature: float = 0.7, 
                  stop: Optional[List[str]] = None, tools: Optional[List[Dict[str, Any]]] = None):
        """Generate a response based on the prompt.
        
        Returns:
            dict with keys 'text' (or 'tool_calls') and 'usage' (token usage information).
        """
        try:
            if not self._initialized:
                if not self.initialize():
                    error_msg = "Error: ChatGPT client is not initialized. Check OPENAI_API_KEY settings."
                    return {'text': error_msg, 'usage': {}}
            
            try:
                assert self.client is not None
                # Determine which parameter to use for token limit
                completion_params = {}
                if any(model in self.model_name.lower() for model in self.models_using_max_completion_tokens):
                    completion_params['max_completion_tokens'] = max_tokens
                else:
                    completion_params['max_tokens'] = max_tokens
                
                if tools:
                    completion_params['tools'] = tools

                
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                    temperature=temperature,
                    stop=stop or [],
                    **completion_params
                )
                
                # Extract text, tool calls and token usage information
                choice = response.choices[0]
                text_content = choice.message.content.strip() if choice.message.content else ""
                
                result_dict = {'usage': {
                    'prompt_tokens': response.usage.prompt_tokens if hasattr(response.usage, 'prompt_tokens') else 0,
                    'completion_tokens': response.usage.completion_tokens if hasattr(response.usage, 'completion_tokens') else 0,
                    'total_tokens': response.usage.total_tokens if hasattr(response.usage, 'total_tokens') else 0
                }}
                
                if choice.message.tool_calls:
                    # Serialize tool calls for the caller
                    tool_calls = []
                    for tc in choice.message.tool_calls:
                        tool_calls.append({
                            'id': tc.id,
                            'function': {
                                'name': tc.function.name,
                                'arguments': tc.function.arguments
                            }
                        })
                    result_dict['tool_calls'] = tool_calls
                else:
                    result_dict['text'] = text_content
                    
                return result_dict
            except Exception as e:
                error_msg = str(e)
                logger.exception(f"Error during generation via ChatGPT: {e}")
                return {'text': f"Error generating response: {error_msg}", 'usage': {}}
        except Exception as e:
            logger.exception(f"Critical error during generation: {e}")
            return {'text': f"Critical error: {str(e)}", 'usage': {}}

    def _generate_with_messages(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: int = 512,
        temperature: float = 0.7,
        stop: Optional[List[str]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Generate a response from a prepared OpenAI messages list."""
        try:
            if not self._initialized:
                if not self.initialize():
                    error_msg = "Error: ChatGPT client is not initialized. Check OPENAI_API_KEY settings."
                    return {'text': error_msg, 'usage': {}}

            assert self.client is not None
            completion_params = self._completion_kwargs(max_tokens)
            if tools:
                completion_params['tools'] = tools

            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=temperature,
                stop=stop or [],
                **completion_params
            )

            choice = response.choices[0]
            text_content = choice.message.content.strip() if choice.message.content else ""

            result_dict = {'usage': {
                'prompt_tokens': response.usage.prompt_tokens if hasattr(response.usage, 'prompt_tokens') else 0,
                'completion_tokens': response.usage.completion_tokens if hasattr(response.usage, 'completion_tokens') else 0,
                'total_tokens': response.usage.total_tokens if hasattr(response.usage, 'total_tokens') else 0
            }}

            if choice.message.tool_calls:
                tool_calls = []
                for tc in choice.message.tool_calls:
                    tool_calls.append({
                        'id': tc.id,
                        'function': {
                            'name': tc.function.name,
                            'arguments': tc.function.arguments
                        }
                    })
                result_dict['tool_calls'] = tool_calls
            else:
                result_dict['text'] = text_content

            return result_dict
        except Exception as e:
            logger.exception("Error during generation with messages via ChatGPT: %s", e)
            return {'text': f"Error generating response: {e}", 'usage': {}}

    @staticmethod
    def _merge_openai_usage(acc: Dict[str, int], usage: Any) -> None:
        if not usage:
            return
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            val = getattr(usage, key, None)
            if val is not None:
                acc[key] = int(acc.get(key, 0)) + int(val)

    def _completion_kwargs(self, max_tokens: int) -> Dict[str, Any]:
        completion_params: Dict[str, Any] = {}
        if any(m in self.model_name.lower() for m in self.models_using_max_completion_tokens):
            completion_params["max_completion_tokens"] = max_tokens
        else:
            completion_params["max_tokens"] = max_tokens
        return completion_params

    def _analyze_with_tool_agent(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_executor: AnalysisToolExecutor,
        max_tokens: int,
        temperature: float,
        stop: Optional[List[str]],
    ) -> Dict[str, Any]:
        """
        Multi-turn ReAct-style loop: model may call tools repeatedly; tool results
        are sent back as `role: tool` messages until the model returns plain text.
        """
        if not self._initialized and not self.initialize():
            return {
                "text": "Error: ChatGPT client is not initialized. Check OPENAI_API_KEY settings.",
                "usage": {},
                "table_data": None,
            }

        messages = list(messages or [])
        if not messages:
            return {
                "text": "Error: no messages provided for analysis.",
                "usage": {},
                "table_data": None,
            }
        usage_acc: Dict[str, int] = {}
        table_data: Optional[Dict[str, Any]] = None

        try:
            assert self.client is not None
            for round_idx in range(MAX_TOOL_AGENT_ROUNDS):
                completion_params = self._completion_kwargs(max_tokens)
                completion_params["tools"] = tools

                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=temperature,
                    stop=stop or [],
                    **completion_params,
                )
                self._merge_openai_usage(usage_acc, getattr(response, "usage", None))

                choice = response.choices[0].message

                if choice.tool_calls:
                    serialized_calls: List[Dict[str, Any]] = []
                    api_tool_calls: List[Dict[str, Any]] = []
                    for tc in choice.tool_calls:
                        serialized_calls.append(
                            {
                                "id": tc.id,
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments or "{}",
                                },
                            }
                        )
                        api_tool_calls.append(
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments or "{}",
                                },
                            }
                        )

                    assistant_msg: Dict[str, Any] = {
                        "role": "assistant",
                        "content": choice.content or "",
                        "tool_calls": api_tool_calls,
                    }
                    messages.append(assistant_msg)

                    tool_msgs, td = tool_executor(serialized_calls)
                    if td:
                        table_data = td
                    for tm in tool_msgs:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tm["id"],
                                "content": tm.get("content") or "",
                            }
                        )
                    logger.info(
                        "Tool agent round %s: %s tool result(s)",
                        round_idx + 1,
                        len(tool_msgs),
                    )
                    continue

                text = (choice.content or "").strip()
                return {"text": text, "usage": usage_acc, "table_data": table_data}

            return {
                "text": (
                    "Could not finish analysis within the maximum number of tool rounds. "
                    "Try a narrower question or period."
                ),
                "usage": usage_acc,
                "table_data": table_data,
            }
        except Exception as e:
            logger.exception("Tool agent loop failed: %s", e)
            return {
                "text": f"Error during tool agent analysis: {e}",
                "usage": usage_acc,
                "table_data": table_data,
            }

    def _analyze_data_agent_stream(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        tool_executor: AnalysisToolExecutor,
        max_tokens: int,
        temperature: float,
        stop: Optional[List[str]],
    ):
        """Run full tool agent non-streaming, then chunk the final text for SSE consumers."""
        res = self._analyze_with_tool_agent(
            messages, tools, tool_executor, max_tokens, temperature, stop
        )
        text = res.get("text") or ""
        usage = res.get("usage") or {}
        td = res.get("table_data")
        n = len(text)
        if n == 0:
            yield {"chunk": "", "usage": usage, "done": True, "agent_table_data": td}
            return
        step = max(32, min(256, n // 24 or 32))
        for i in range(0, n, step):
            yield {"chunk": text[i : i + step], "usage": usage}
        yield {"chunk": "", "usage": usage, "done": True, "agent_table_data": td}
    
    def analyze_data(
        self,
        data_summary: Dict[str, Any],
        question: str = "",
        use_streaming: bool = False,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        lang: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_executor: Optional[AnalysisToolExecutor] = None,
    ):
        """Analyze data using ChatGPT.
        
        Args:
            data_summary: Data summary for analysis.
            question: Analysis question.
            use_streaming: If True, returns a generator for streaming responses.
            conversation_history: Optional list of previous messages [{"role": "user"|"assistant", "content": "..."}].
            tools: Optional OpenAI tools schema.
            tool_executor: When set with ``tools``, runs multi-turn tool results (ReAct loop).
                Callable taking serialized tool_calls list, returning
                ``(list of {"id","content"} for role=tool, optional table dict for UI)``.
        
        Returns:
            If use_streaming is False: dict with keys 'text' and 'usage' (token usage info).
            If use_streaming is True: generator that yields response chunks (the last chunk contains usage).
            With ``tool_executor``, dict may include ``table_data`` (non-streaming) or last chunk
            ``agent_table_data`` (streaming).
        """
        messages = self._build_analysis_messages(
            data_summary,
            question,
            conversation_history=conversation_history,
            lang=lang,
        )
        
        # For free-form answers we use more tokens (up to 4096); for code we would usually use fewer (around 2048).
        # Increase the limit because free-form answers can be longer.
        max_tokens = 4096  # Up to 4096 tokens for free-form answers and analysis
        
        stop_tokens = [
            "\n\n\n\n",  # Multiple consecutive empty lines
            "```\n\n```",  # Empty code block
        ]
        
        # Lower temperature improves instruction-following (code fence first, real numbers).
        temperature = 0.35

        if tools and tool_executor is not None:
            if use_streaming:
                return self._analyze_data_agent_stream(
                    messages, tools, tool_executor, max_tokens, temperature, stop_tokens
                )
            return self._analyze_with_tool_agent(
                messages, tools, tool_executor, max_tokens, temperature, stop_tokens
            )
        
        if use_streaming:
            return self.generate_stream(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=stop_tokens,
                tools=tools,
            )
        else:
            return self._generate_with_messages(
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stop=stop_tokens,
                tools=tools,
            )
    
    def generate_stream(self, prompt: Optional[str] = None, max_tokens: int = 512, temperature: float = 0.7, 
                       stop: Optional[List[str]] = None, tools: Optional[List[Dict[str, Any]]] = None,
                       messages: Optional[List[Dict[str, Any]]] = None):
        """Generate a response via streaming (incremental chunks)."""
        if not self._initialized:
            if not self.initialize():
                error_msg = "Error: ChatGPT client is not initialized. Check OPENAI_API_KEY settings."
                yield {'chunk': error_msg, 'usage': {}}
                return
        
        try:
            assert self.client is not None
            # Determine which parameter to use for the token limit
            completion_params = {}
            if any(model in self.model_name.lower() for model in self.models_using_max_completion_tokens):
                completion_params['max_completion_tokens'] = max_tokens
            else:
                completion_params['max_tokens'] = max_tokens
            
            if tools:
                completion_params['tools'] = tools
            
            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages if messages is not None else [
                    {"role": "user", "content": prompt or ""}
                ],
                temperature=temperature,
                stop=stop or [],
                stream=True,
                **completion_params
            )
            
            accumulated_text = ""
            token_info = {}
            
            is_tool_call = False
            tool_calls_acc = {}
            
            for chunk in stream:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    
                    if not is_tool_call and getattr(delta, 'tool_calls', None):
                        is_tool_call = True
                    
                    if is_tool_call:
                        if hasattr(delta, 'tool_calls') and delta.tool_calls:
                            for tc in delta.tool_calls:
                                idx = tc.index
                                if idx not in tool_calls_acc:
                                    tool_calls_acc[idx] = {'id': tc.id, 'function': {'name': tc.function.name, 'arguments': ''}}
                                if tc.function.arguments:
                                    tool_calls_acc[idx]['function']['arguments'] += tc.function.arguments
                    else:
                        if delta.content:
                            content = delta.content
                            accumulated_text += content
                            yield {'chunk': content, 'usage': token_info.copy()}
                
                # Update token usage information when available
                if hasattr(chunk, 'usage') and chunk.usage:
                    token_info = {
                        'prompt_tokens': chunk.usage.prompt_tokens if hasattr(chunk.usage, 'prompt_tokens') else 0,
                        'completion_tokens': chunk.usage.completion_tokens if hasattr(chunk.usage, 'completion_tokens') else 0,
                        'total_tokens': chunk.usage.total_tokens if hasattr(chunk.usage, 'total_tokens') else 0
                    }
            
            # Send final usage
            if not token_info or token_info.get('total_tokens', 0) == 0:
                prompt_size = len(prompt or "")
                if messages:
                    prompt_size = sum(len(str(m.get("content") or "")) for m in messages)
                estimated_tokens = prompt_size // 4 + len(accumulated_text) // 4
                token_info = {
                    'prompt_tokens': prompt_size // 4,
                    'completion_tokens': len(accumulated_text) // 4,
                    'total_tokens': estimated_tokens
                }
            
            if is_tool_call:
                # Tell the caller that a tool call was requested
                yield {'tool_calls': list(tool_calls_acc.values()), 'usage': token_info, 'done': True}
            else:
                yield {'chunk': '', 'usage': token_info, 'done': True}
            
        except Exception as e:
            logger.exception(f"Error during streaming generation via ChatGPT: {e}")
            yield {'chunk': f"Error: {str(e)}", 'usage': {}}
    
    def generate_chart_suggestion(self, data_summary: Dict[str, Any], lang: str = "ru") -> Dict[str, Any]:
        """Generate a chart suggestion based on the given data summary."""
        lang = lang if lang in ("ru", "uk", "en") else "ru"
        prompt = self._build_chart_prompt(data_summary, lang=lang)
        response = self.generate(prompt, max_tokens=512, temperature=0.3)
        
        # Try to parse JSON from the response
        try:
            text = response.get('text', '') if isinstance(response, dict) else response
            # Look for JSON in the response text
            json_start = text.find('{')
            json_end = text.rfind('}') + 1
            if json_start != -1 and json_end > json_start:
                json_str = text[json_start:json_end]
                return json.loads(json_str)
        except:
            pass
        
        # If parsing fails, return a basic structure
        return {
            "chart_type": "bar",
            "title": "Data analysis",
            "description": response.get('text', '') if isinstance(response, dict) else str(response),
            "labels": [],
            "datasets": []
        }
    
    def generate_insights(self, table_data: Dict[str, Any], question: str = "") -> str:
        """Generate insights and recommendations based on table data.
        
        Args:
            table_data: Table data in the form {headers: [...], rows: [...]}.
            question: Optional original user question.
        
        Returns:
            Text with insights and recommendations.
        """
        prompt = self._build_insights_prompt(table_data, question)
        
        stop_tokens = [
            "\n\n\n\n",  # Multiple consecutive empty lines
        ]
        
        result = self.generate(prompt, max_tokens=4096, temperature=0.7, stop=stop_tokens)
        
        # The generate method returns a dict with keys 'text' and 'usage'
        if isinstance(result, dict):
            text = result.get('text', '')
            if not text:
                text = result.get('response', result.get('content', ''))
            if not text:
                text = "Failed to generate insights. Please try again."
        elif isinstance(result, str):
            text = result
        else:
            logger.warning(f"generate_insights got unexpected result type: {type(result)}")
            text = str(result) if result else "Failed to generate insights. Please try again."
        
        return text
    
    def _build_insights_prompt(self, table_data: Dict[str, Any], question: str = "") -> str:
        """Build a prompt for generating insights and recommendations."""
        answer_lang = self._detect_language(question)
        i18n = self._i18n(answer_lang)

        headers = table_data.get('headers', [])
        rows = table_data.get('rows', [])
        
        # Format table data for the prompt
        table_text = f"{i18n['headers']}: " + ", ".join(headers) + "\n\n"
        table_text += f"{i18n['data']}:\n"
        
        # Add the first 20 rows for analysis (to avoid overloading the prompt)
        max_rows = min(20, len(rows))
        for i, row in enumerate(rows[:max_rows]):
            row_text = " | ".join([str(cell) if cell is not None else "" for cell in row])
            table_text += f"{i+1}. {row_text}\n"
        
        if len(rows) > max_rows:
            table_text += "\n" + i18n["total_rows_fmt"].format(n=len(rows)) + "\n"

        prompt = f"""You are a data analysis expert and business consultant.

{self._language_policy_block()}
{self._no_placeholder_numbers_block()}
Answer language: {answer_lang}

Use these section titles (in the answer language), but keep each section SHORT:
- {i18n['section_key_findings']} — max 3 bullets; cite numbers once, do not repeat the whole table
- {i18n['section_trend_analysis']} — max 2 bullets
- {i18n['section_problem_areas']} — max 2 bullets
- {i18n['section_recommendations']} — max 3 bullets

Do not duplicate the table as markdown in your answer; the user already sees the table.
Every number and name in your text must appear verbatim from the table above (no X/Y/A/B/Z).

Table data:
{table_text}
"""
        
        if question:
            prompt += f"{i18n['user_question']}: {question}\n\n"
        
        prompt += f"""{self._language_policy_block()}
Quality requirements:
- Total length roughly under 250 words unless the user explicitly asked for a long report
- No markdown pipe tables; prose and bullets only
- Complete all four sections with the bullet limits above

{i18n['conclusions']}:"""
        
        return prompt
    
    def _build_analysis_messages(
        self,
        data_summary: Dict[str, Any],
        question: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        lang: Optional[str] = None,
    ) -> List[Dict[str, str]]:
        """Build structured messages for data analysis (Function Calling).

        IMPORTANT: For data-heavy tasks, the model MUST call the provided tools.
        conversation_history: optional — previous messages to continue the dialog.
        """
        logger.info(
            "Building data-analysis prompt. Question: %s",
            (question[:100] if question else "—"),
        )
        
        if lang:
            lang_norm = (lang or "").split("-")[0].lower()
            answer_lang = lang_norm if lang_norm in ("ru", "uk", "en") else "ru"
        else:
            answer_lang = self._detect_language(question)
        i18n = self._i18n(answer_lang)

        period_hint = ""
        try:
            period = (data_summary or {}).get("period")
            if period:
                period_hint = (
                    "\n═══════════════════════════════════════════════════════════════\n"
                    "UI FILTER SCOPE (querysets match the main dashboard filters; do not assume a broader DB slice):\n"
                    f"{json.dumps(period, ensure_ascii=False)}\n"
                    "═══════════════════════════════════════════════════════════════\n"
                )
        except Exception:
            period_hint = ""

        system_msg = f"""You are a data analysis expert and business consultant working with a CRM database.

{self._language_policy_block()}
{self._no_placeholder_numbers_block()}
Answer language: {answer_lang}
{period_hint}
═══════════════════════════════════════════════════════════════
AVAILABLE TOOLS (FUNCTION CALLING):
═══════════════════════════════════════════════════════════════
- You have access to database analytic functions (tools).
- If the user asks for ANY number from the database (e.g. sales, comparisons, top managers, amounts, deals, expenses, salary payouts), you MUST call the provided tools.
- If one question asks for BOTH salary/payout totals AND expenses (e.g. year summary), call tools for ``salary_payments`` and ``expenses`` (or use two aggregate calls). Do not answer with only one of them unless the user asked for a single stream.
- Per-deal manager compensation (Ukr./Rus. e.g. "зарплата по сделкам", "кому скільки зарплати з угод", "сколько заработали на сделках" in the sense of CRM accrual) is the ``salary`` field on **sales** records. Use ``crm_analytics_aggregate`` with ``dataset: \"sales\"``, ``sales_amount_field: \"salary\"``, optional ``company_name_contains`` for the client company name, and ``group_by: \"manager\"`` when needed. Do **not** use ``salary_payments`` for that — that dataset is bank payouts without per-deal company linkage.
- NEVER try to guess or hallucinate numbers. If you don't have the data, call a tool first.
- The tools already apply the UI filters (dates, managers context). So if the user says "in May", pass months=[5] to the tool.

CRITICAL FOR REPORTING DATA:
- You may use several tool rounds: call tools again if you need another dataset or dimension
  (e.g. sales totals, then expenses by type, then salary payments) before answering.
- Once you have enough tool results, answer in natural language with factual numbers and stop calling tools.
- For managers use their real names from the data.
- Keep responses concise. Don't write a long preamble.
- If the user asks "why", answer using facts returned by the tools (did one manager drop, did the average deal fall, etc.).
- The web UI automatically draws bar/line charts from tabular tool results when appropriate.
  Do NOT claim you cannot display charts; give numbers in text and let the UI show the graphic when a table is returned.
"""

        out_messages: List[Dict[str, str]] = [{"role": "system", "content": system_msg}]

        # Keep only recent dialog context to avoid prompt overload.
        if conversation_history:
            recent = conversation_history[-MAX_HISTORY_MESSAGES:]
            for msg in recent:
                role = msg.get("role", "")
                if role not in ("user", "assistant"):
                    continue
                content = (msg.get("content") or "").strip()
                tbl = (
                    msg.get("table_data")
                    or msg.get("table")
                    or msg.get("tableData")
                    or msg.get("table_data_json")
                )

                # Compact table preview in assistant message to ground follow-up questions.
                table_note = ""
                try:
                    if isinstance(tbl, dict) and tbl.get("headers") and tbl.get("rows"):
                        headers = [str(h) for h in (tbl.get("headers") or [])[:20]]
                        rows = tbl.get("rows") or []
                        preview_lines = []
                        max_rows = min(5, len(rows))
                        for row in rows[:max_rows]:
                            if isinstance(row, (list, tuple)):
                                preview_lines.append(" | ".join([str(c) if c is not None else "" for c in row[:20]]))
                            elif isinstance(row, dict):
                                preview_lines.append(" | ".join([str(row.get(h, "")) for h in headers]))
                            else:
                                preview_lines.append(str(row))
                        table_note = (
                            "\n[table context]\n"
                            + "Headers: "
                            + ", ".join(headers)
                            + "\n"
                            + "\n".join(preview_lines)
                        )
                        if len(rows) > max_rows:
                            table_note += f"\n... ({len(rows)} total rows)"
                    elif isinstance(tbl, str) and tbl.strip():
                        table_note = "\n[table context]\n" + tbl.strip()[:1200]
                except Exception:
                    table_note = ""

                msg_content = (content[:4000] + ("..." if len(content) > 4000 else "")) if content else ""
                merged = (msg_content + table_note).strip()
                if merged:
                    out_messages.append({"role": role, "content": merged})

        out_messages.append({
            "role": "user",
            "content": question if question else "Analyze the data",
        })
        return out_messages
        

    def _build_chart_prompt(self, data_summary: Dict[str, Any], lang: str = "ru") -> str:
        """Build the prompt for generating a chart suggestion."""
        answer_lang = lang if lang in ("ru", "uk", "en") else "ru"

        # Keep a single English JSON schema example and enforce language via rules below.
        # This avoids mixing languages in the prompt text while still requiring localized output.
        json_template = """{
    "chart_type": "bar|line|pie|doughnut",
    "title": "Chart title",
    "description": "What the chart shows",
    "labels": ["label1", "label2", "..."],
    "datasets": [
        {
            "label": "Dataset name",
            "data": [value1, value2, "..."]
        }
    ]
}"""

        prompt = f"""You are a data visualization expert. Based on the following data, propose the optimal chart type and structure.

{self._language_policy_block()}
Answer language: {answer_lang}

Data:
{json.dumps(data_summary, ensure_ascii=False, indent=2)}

Return ONLY valid JSON in this schema (no extra text):
{json_template}

CRITICAL: Output must be valid JSON only.
- All human-readable text fields (title, description, labels, datasets[].label) must be in the selected answer language ({answer_lang}):
  - ru: Russian
  - uk: Ukrainian
  - en: English
"""
        return prompt


# Global LLM service singleton
_llm_service = None

def get_llm_service() -> LLMService:
    """Get global singleton instance of LLM service."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
