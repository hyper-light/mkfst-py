import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional, Type, TypeVar

from mkfst.env import Env
from mkfst.env.time_parser import TimeParser
from mkfst.snowflake import SnowflakeGenerator

from .cancel import cancel
from .task import Task as MkfstTask

T = TypeVar('T')

class TaskRunner:

    def __init__(
            self, 
            instance_id: int,
            config: Env
    ) -> None:
        self.tasks: Dict[str, MkfstTask[Any]] = {}
        self.results: Dict[str, Any]
        self._runner = ThreadPoolExecutor(max_workers=config.MERCURY_SYNC_TASK_RUNNER_MAX_THREADS)
        self._cleanup_interval = TimeParser(config.MERCURY_SYNC_CLEANUP_INTERVAL).time
        self._cleanup_task: Optional[asyncio.Task] = None
        self._run_cleanup: bool = False
        self._snowflake_generator = SnowflakeGenerator(instance_id)

    def all_tasks(self):
        for task in self.tasks.values():
            yield task

    def start_cleanup(self):
        self._run_cleanup = True
        self._cleanup_task = asyncio.create_task(
            self._cleanup()
        )

    def create_task_id(self):
        return self._snowflake_generator.generate()
        
    def add(
        self,
        task: Type[T]
    ):
        runnable = MkfstTask(
            task,
            self._snowflake_generator
        )
        self.tasks[runnable.name] = runnable

    def run(
        self,
        task_name: str,
        *args,
        run_id: Optional[int]=None,
        **kwargs
    ):

        task = self.tasks.get(task_name)
        if task and task.repeat == 'NEVER':
            return task.run(
                *args,
                **kwargs,
                run_id=run_id
            )

        elif task and task.schedule:
            return task.run_schedule(
                *args,
                **kwargs,
                run_id=run_id
            )
        
    def get_task_status(
        self,
        task_name: str
    ):
        if task := self.tasks.get(task_name):
            return task.status
        
    def get_run_status(
        self,
        task_name: str,
        run_id: str
    ):
        if task := self.tasks.get(task_name):
            return task.get_run_status(run_id)

    async def complete(
        self,
        task_name: str,
        run_id: str
    ):
        if task := self.tasks.get(task_name):
            return await task.complete(run_id)
    
    async def cancel(
        self,
        task_name: str,
        run_id: str

    ):
        task = self.tasks.get(task_name)
        if task:
            await task.cancel(run_id)
        
    async def cancel_schedule(
        self,
        task_name: str,
    ):

        task = self.tasks.get(task_name)
        if task:
            await task.cancel_schedule()

    async def shutdown(self):
        for task in self.tasks.values():
            await task.shutdown()

        self._run_cleanup = False
        await cancel(self._cleanup_task)

    async def _cleanup(self):
        while self._run_cleanup:
            await self._cleanup_scheduled_tasks()
            await asyncio.sleep(self._cleanup_interval)
    
    async def _cleanup_scheduled_tasks(self):

        try:
            for task in self.tasks.values():
                await task.cleanup()

        except Exception:
            pass

            

        

            




