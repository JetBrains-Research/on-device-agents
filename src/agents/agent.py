from __future__ import annotations

import json
import logging
from abc import abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import yaml
from langchain.agents.agent import AgentOutputParser, BaseSingleActionAgent
from langchain.agents.agent_types import AgentType
from langchain.callbacks.base import BaseCallbackManager
from langchain.callbacks.manager import Callbacks
from langchain.prompts.few_shot import FewShotPromptTemplate
from langchain.prompts.prompt import PromptTemplate
from langchain.pydantic_v1 import root_validator
from langchain.schema import (
    AgentAction,
    AgentFinish,
    BaseOutputParser,
    BasePromptTemplate,
)
from langchain.schema.language_model import BaseLanguageModel
from langchain.schema.messages import BaseMessage
from langchain.tools import BaseTool

from src.chains.llm_chain import LLMChain

logger = logging.getLogger(__name__)


class AgentOutputParser(BaseOutputParser):
    """Base class for parsing agent output into agent action/finish."""

    @abstractmethod
    def parse(self, text: str) -> Union[AgentAction, AgentFinish]:
        """Parse text into agent action/finish."""


class Agent(BaseSingleActionAgent):
    """Agent that calls the language model and deciding the action.

    This is driven by an LLMChain. The prompt in the LLMChain MUST include
    a variable called "agent_scratchpad" where the agent can put its
    intermediary work.

    Copied from Langchain v0.0.283,
    but merged with the parent class BaseSingleActionAgent for simplicity.
    """

    llm_chain: LLMChain
    output_parser: AgentOutputParser
    allowed_tools: Optional[List[str]] = None

    @property
    def _agent_type(self) -> str:
        """Return Identifier of agent type."""
        raise NotImplementedError

    def dict(self, **kwargs: Any) -> Dict:
        """Return dictionary representation of agent."""
        _dict = super().dict()
        _type = self._agent_type
        if isinstance(_type, AgentType):
            _dict["_type"] = str(_type.value)
        else:
            _dict["_type"] = _type
        del _dict["output_parser"]
        return _dict

    def get_allowed_tools(self) -> Optional[List[str]]:
        return self.allowed_tools

    @property
    def return_values(self) -> List[str]:
        return ["output"]

    def _fix_text(self, text: str) -> str:
        """Fix the text."""
        raise ValueError("fix_text not implemented for this agent.")

    @property
    def _stop(self) -> List[str]:
        return [
            f"\n{self.observation_prefix.rstrip()}",
            f"\n\t{self.observation_prefix.rstrip()}",
        ]

    def _construct_scratchpad(
        self, intermediate_steps: List[Tuple[AgentAction, str]]
    ) -> Union[str, List[BaseMessage]]:
        """Construct the scratchpad that lets the agent continue its thought process."""
        thoughts = ""
        for action, observation in intermediate_steps:
            thoughts += action.log
            thoughts += f"\n{self.observation_prefix}{observation}\n{self.llm_prefix}"
        return thoughts

    def plan(
        self,
        intermediate_steps: List[Tuple[AgentAction, str]],
        callbacks: Callbacks = None,
        **kwargs: Any,
    ) -> Union[AgentAction, AgentFinish]:
        """Given input, decided what to do.

        Args:
            intermediate_steps: Steps the LLM has taken to date,
                along with observations
            callbacks: Callbacks to run.
            **kwargs: User inputs.

        Returns:
            Action specifying what tool to use.
        """
        try:
            full_inputs = self.get_full_inputs(intermediate_steps, **kwargs)
            full_output = self.llm_chain.predict(callbacks=callbacks, **full_inputs)
            return self.output_parser.parse(full_output)
        except Exception as e:
            full_inputs["agent_scratchpad"] = (
                full_inputs["agent_scratchpad"] + full_output + "\nAction: "
            )
            full_output = self.llm_chain.predict(callbacks=callbacks, **full_inputs)
            return self.output_parser.parse("Action: " + full_output)

    async def aplan(
        self,
        intermediate_steps: List[Tuple[AgentAction, str]],
        callbacks: Callbacks = None,
        **kwargs: Any,
    ) -> Union[AgentAction, AgentFinish]:
        """Given input, decided what to do.

        Args:
            intermediate_steps: Steps the LLM has taken to date,
                along with observations
            callbacks: Callbacks to run.
            **kwargs: User inputs.

        Returns:
            Action specifying what tool to use.
        """
        try:
            full_inputs = self.get_full_inputs(intermediate_steps, **kwargs)
            full_output = await self.llm_chain.apredict(
                callbacks=callbacks, **full_inputs
            )
            agent_output = await self.output_parser.aparse(full_output)
        except Exception as e:
            full_inputs["agent_scratchpad"] = (
                full_inputs["agent_scratchpad"] + full_output + "\nAction: "
            )
            full_output = await self.llm_chain.apredict(
                callbacks=callbacks, **full_inputs
            )
            agent_output = await self.output_parser.aparse("Action: " + full_output)

        return agent_output

    def get_full_inputs(
        self, intermediate_steps: List[Tuple[AgentAction, str]], **kwargs: Any
    ) -> Dict[str, Any]:
        """Create the full inputs for the LLMChain from intermediate steps."""
        thoughts = self._construct_scratchpad(intermediate_steps)
        new_inputs = {"agent_scratchpad": thoughts, "stop": self._stop}
        full_inputs = {**kwargs, **new_inputs}
        return full_inputs

    @property
    def input_keys(self) -> List[str]:
        """Return the input keys.

        :meta private:
        """
        return list(set(self.llm_chain.input_keys) - {"agent_scratchpad"})

    @root_validator()
    def validate_prompt(cls, values: Dict) -> Dict:
        """Validate that prompt matches format."""
        prompt = values["llm_chain"].prompt
        if "agent_scratchpad" not in prompt.input_variables:
            logger.warning(
                "`agent_scratchpad` should be a variable in prompt.input_variables."
                " Did not find it, so adding it at the end."
            )
            prompt.input_variables.append("agent_scratchpad")
            if isinstance(prompt, PromptTemplate):
                prompt.template += "\n{agent_scratchpad}"
            elif isinstance(prompt, FewShotPromptTemplate):
                prompt.suffix += "\n{agent_scratchpad}"
            else:
                raise ValueError(f"Got unexpected prompt type {type(prompt)}")
        return values

    @property
    @abstractmethod
    def observation_prefix(self) -> str:
        """Prefix to append the observation with."""

    @property
    @abstractmethod
    def llm_prefix(self) -> str:
        """Prefix to append the LLM call with."""

    @classmethod
    def _validate_tools(cls, tools: Sequence[BaseTool]) -> None:
        """Validate that appropriate tools are passed in."""
        pass

    @classmethod
    @abstractmethod
    def _get_default_output_parser(cls, **kwargs: Any) -> AgentOutputParser:
        """Get default output parser for this class."""

    @classmethod
    def from_llm_and_tools(
        cls,
        llm: BaseLanguageModel,
        tools: Sequence[BaseTool],
        prompt: BasePromptTemplate,
        callback_manager: Optional[BaseCallbackManager] = None,
        output_parser: Optional[AgentOutputParser] = None,
        **kwargs: Any,
    ) -> Agent:
        """Construct an agent from an LLM and tools."""
        cls._validate_tools(tools)
        llm_chain = LLMChain(
            llm=llm,
            prompt=prompt,
            callback_manager=callback_manager,
        )
        tool_names = [tool.name for tool in tools]
        _output_parser = output_parser or cls._get_default_output_parser()
        return cls(
            llm_chain=llm_chain,
            allowed_tools=tool_names,
            output_parser=_output_parser,
            **kwargs,
        )

    def return_stopped_response(
        self,
        early_stopping_method: str,
        intermediate_steps: List[Tuple[AgentAction, str]],
        **kwargs: Any,
    ) -> AgentFinish:
        """Return response when agent has been stopped due to max iterations."""
        if early_stopping_method == "force":
            # `force` just returns a constant string
            return AgentFinish(
                {"output": "Agent stopped due to iteration limit or time limit."}, ""
            )
        elif early_stopping_method == "generate":
            # Generate does one final forward pass
            thoughts = ""
            for action, observation in intermediate_steps:
                thoughts += action.log
                thoughts += (
                    f"\n{self.observation_prefix}{observation}\n{self.llm_prefix}"
                )
            # Adding to the previous steps, we now tell the LLM to make a final pred
            thoughts += (
                "\n\nI now need to return a final answer based on the previous steps:"
            )
            new_inputs = {"agent_scratchpad": thoughts, "stop": self._stop}
            full_inputs = {**kwargs, **new_inputs}
            full_output = self.llm_chain.predict(**full_inputs)
            # We try to extract a final answer
            parsed_output = self.output_parser.parse(full_output)
            if isinstance(parsed_output, AgentFinish):
                # If we can extract, we send the correct stuff
                return parsed_output
            else:
                # If we can extract, but the tool is not the final tool,
                # we just return the full output
                return AgentFinish({"output": full_output}, full_output)
        else:
            raise ValueError(
                "early_stopping_method should be one of `force` or `generate`, "
                f"got {early_stopping_method}"
            )

    def tool_run_logging_kwargs(self) -> Dict:
        return {
            "llm_prefix": self.llm_prefix,
            "observation_prefix": self.observation_prefix,
        }

    def save(self, file_path: Union[Path, str]) -> None:
        """Save the agent.

        Args:
            file_path: Path to file to save the agent to.

        Example:
        .. code-block:: python

            # If working with agent executor
            agent.agent.save(file_path="path/agent.yaml")
        """
        # Convert file to Path object.
        if isinstance(file_path, str):
            save_path = Path(file_path)
        else:
            save_path = file_path

        directory_path = save_path.parent
        directory_path.mkdir(parents=True, exist_ok=True)

        # Fetch dictionary to save
        agent_dict = self.dict()

        if save_path.suffix == ".json":
            with open(file_path, "w") as f:
                json.dump(agent_dict, f, indent=4)
        elif save_path.suffix == ".yaml":
            with open(file_path, "w") as f:
                yaml.dump(agent_dict, f, default_flow_style=False)
        else:
            raise ValueError(f"{save_path} must be json or yaml")
