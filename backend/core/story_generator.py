from typing import Any
from sqlalchemy.orm import Session

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

from core.prompts import STORY_PROMPT
from models.story import Story, StoryNode
from core.models import StoryLLMResponse, StoryNodeLLM
from dotenv import load_dotenv
from core.config import settings

load_dotenv()

class StoryGenerator:

    @classmethod
    def _get_llm(cls):
        return ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=settings.GOOGLE_API_KEY)

    @classmethod
    def generate_story(cls, db:Session, session_id: str, theme:str="fantasy")->Story:
        llm=cls._get_llm()
        story_parser=PydanticOutputParser(pydantic_object=StoryLLMResponse)

        prompt=ChatPromptTemplate.from_messages([
            (
                "system",
                STORY_PROMPT
            ),
            (
                "human",
                f"Create the story with this theme:{theme}"
            )
        ]).partial(format_instructions=story_parser.get_format_instructions())

        raw_response=llm.invoke(prompt.invoke({}))

        response_text=raw_response
        if hasattr(raw_response, "content"):
            response_text=raw_response.content

        # Handle list of parts if returned
        if isinstance(response_text, list):
            response_text = "".join(
                part.get("text", "") if isinstance(part, dict) else str(part)
                for part in response_text
            )

        story_structure=story_parser.parse(response_text)

        story_db=Story(title=story_structure.title, session_id=session_id)
        db.add(story_db)
        db.flush()

        root_node_data=story_structure.rootNode
        if isinstance(root_node_data, dict):
            root_node_data=StoryNodeLLM.model_validate(root_node_data)

        cls._process_story_node(db, story_db.id, root_node_data, is_root=True)

        db.commit()
        return story_db

    @classmethod
    def _process_story_node(cls, db:Session, story_id:int, node_data:Any, is_root:bool=False)->StoryNode:
        if isinstance(node_data, dict):
            node_data = StoryNodeLLM.model_validate(node_data)

        content = node_data.content if hasattr(node_data, "content") else node_data["content"]
        is_ending = node_data.isEnding if hasattr(node_data, "isEnding") else node_data.get("isEnding", False)
        is_winning_ending = node_data.isWinningEnding if hasattr(node_data, "isWinningEnding") else node_data.get("isWinningEnding", False)

        node=StoryNode(
            story_id=story_id,
            content=content,
            is_root=is_root,
            is_ending=is_ending,
            is_winning_ending=is_winning_ending,
            options=[]
        )
        db.add(node)
        db.flush()

        options_raw = node_data.options if hasattr(node_data, "options") else node_data.get("options")
        if not node.is_ending and options_raw:
            options_list=[]
            for option_data in options_raw:
                if isinstance(option_data, dict):
                    text = option_data.get("text", "")
                    next_node = option_data.get("nextNode")
                else:
                    text = option_data.text
                    next_node = option_data.nextNode

                if isinstance(next_node, dict):
                    next_node=StoryNodeLLM.model_validate(next_node)

                child_node=cls._process_story_node(db, story_id, next_node, False)

                options_list.append({
                    "text": text,
                    "node_id":child_node.id
                })

            node.options=options_list
            db.flush()

        return node



