from __future__ import absolute_import
from __future__ import unicode_literals

import mock
from testify import assert_equal
from testify import setup_teardown
from testify import TestCase

from tron.mesos import DOCKERCFG_LOCATION
from tron.mesos import MESOS_ROLE
from tron.mesos import MESOS_SECRET
from tron.mesos import MesosCluster
from tron.mesos import MesosTask
from tron.mesos import OFFER_TIMEOUT


def mock_task_event(
    task_id, platform_type, raw=None, terminal=False, success=False, **kwargs
):
    return mock.MagicMock(
        kind='task',
        task_id=task_id,
        platform_type=platform_type,
        raw=raw or {},
        terminal=terminal,
        success=success,
        **kwargs
    )


class MesosTaskTestCase(TestCase):
    @setup_teardown
    def setup(self):
        self.action_run_id = 'my_service.job.1.action'
        self.task_id = '123abcuuid'
        self.task = MesosTask(
            id=self.action_run_id,
            task_config=mock.Mock(
                cmd='echo hello world',
                task_id=self.task_id,
            ),
        )
        # Suppress logging
        with mock.patch.object(self.task, 'log'):
            yield

    def test_handle_staging(self):
        event = mock_task_event(
            task_id=self.task_id,
            platform_type='staging',
        )
        self.task.handle_event(event)
        assert self.task.state == MesosTask.PENDING

    def test_handle_running(self):
        event = mock_task_event(
            task_id=self.task_id,
            platform_type='running',
        )
        self.task.handle_event(event)
        assert self.task.state == MesosTask.RUNNING

    def test_handle_running_for_other_task(self):
        event = mock_task_event(
            task_id='other321',
            platform_type='running',
        )
        self.task.handle_event(event)
        assert self.task.state == MesosTask.PENDING

    def test_handle_finished(self):
        self.task.started()
        event = mock_task_event(
            task_id=self.task_id,
            platform_type='finished',
            terminal=True,
            success=True,
        )
        self.task.handle_event(event)
        assert self.task.is_complete

    def test_handle_failed(self):
        self.task.started()
        event = mock_task_event(
            task_id=self.task_id,
            platform_type='failed',
            terminal=True,
            success=False,
        )
        self.task.handle_event(event)
        assert self.task.is_failed
        assert self.task.is_done

    def test_handle_killed(self):
        self.task.started()
        event = mock_task_event(
            task_id=self.task_id,
            platform_type='killed',
            terminal=True,
            success=False,
        )
        self.task.handle_event(event)
        assert self.task.is_failed
        assert self.task.is_done

    def test_handle_lost(self):
        self.task.started()
        event = mock_task_event(
            task_id=self.task_id,
            platform_type='lost',
            terminal=True,
            success=False,
        )
        self.task.handle_event(event)
        assert self.task.is_failed
        assert self.task.is_done

    def test_handle_error(self):
        self.task.started()
        event = mock_task_event(
            task_id=self.task_id,
            platform_type='error',
            terminal=True,
            success=False,
        )
        self.task.handle_event(event)
        assert self.task.is_failed
        assert self.task.is_done

    def test_handle_unknown_terminal_event(self):
        self.task.started()
        event = mock_task_event(
            task_id=self.task_id,
            platform_type=None,
            terminal=True,
            success=False,
        )
        self.task.handle_event(event)
        assert self.task.is_failed
        assert self.task.is_done

    def test_handle_success_sequence(self):
        self.task.handle_event(
            mock_task_event(
                task_id=self.task_id,
                platform_type='staging',
            )
        )
        self.task.handle_event(
            mock_task_event(
                task_id=self.task_id,
                platform_type='running',
            )
        )
        self.task.handle_event(
            mock_task_event(
                task_id=self.task_id,
                platform_type='finished',
                terminal=True,
                success=True,
            )
        )
        assert self.task.is_complete

    def test_log_event_error(self):
        with mock.patch.object(self.task, 'log_event_info') as mock_log_event:
            mock_log_event.side_effect = Exception
            self.task.handle_event(
                mock_task_event(
                    task_id=self.task_id,
                    platform_type='running',
                )
            )
            assert mock_log_event.called
        assert self.task.state == MesosTask.RUNNING


class MesosClusterTestCase(TestCase):
    @setup_teardown
    def setup_mocks(self):
        with mock.patch(
            'tron.mesos.PyDeferredQueue',
            autospec=True,
        ) as queue_cls, mock.patch(
            'tron.mesos.TaskProcessor',
            autospec=True,
        ) as processor_cls, mock.patch(
            'tron.mesos.Subscription',
            autospec=True,
        ) as runner_cls, mock.patch(
            'tron.mesos.get_mesos_leader',
            autospec=True,
        ) as mock_get_leader:
            self.mock_queue = queue_cls.return_value
            self.mock_processor = processor_cls.return_value
            self.mock_runner_cls = runner_cls
            self.mock_runner_cls.return_value.stopping = False
            self.mock_get_leader = mock_get_leader
            yield

    @mock.patch('tron.mesos.socket', autospec=True)
    def test_init(self, mock_socket):
        mock_socket.gethostname.return_value = 'hostname'
        cluster = MesosCluster('mesos-cluster-a.me')

        assert_equal(cluster.queue, self.mock_queue)
        assert_equal(cluster.processor, self.mock_processor)

        self.mock_get_leader.assert_called_once_with('mesos-cluster-a.me')
        self.mock_processor.executor_from_config.assert_called_once_with(
            provider='mesos',
            provider_config={
                'secret': MESOS_SECRET,
                'mesos_address': self.mock_get_leader.return_value,
                'role': MESOS_ROLE,
                'framework_name': 'tron-hostname',
            },
        )
        self.mock_runner_cls.assert_called_once_with(
            self.mock_processor.executor_from_config.return_value,
            self.mock_queue,
        )
        assert_equal(cluster.runner, self.mock_runner_cls.return_value)

        get_event_deferred = cluster.deferred
        assert_equal(get_event_deferred, self.mock_queue.get.return_value)
        get_event_deferred.addCallback.assert_has_calls(
            [
                mock.call(cluster._process_event),
                mock.call(cluster.handle_next_event),
            ]
        )

    def test_submit(self):
        cluster = MesosCluster('mesos-cluster-a.me')
        mock_task = mock.MagicMock(spec_set=MesosTask)
        mock_task.get_mesos_id.return_value = 'this_task'
        cluster.submit(mock_task)

        assert 'this_task' in cluster.tasks
        assert_equal(cluster.tasks['this_task'], mock_task)
        cluster.runner.run.assert_called_once_with(
            mock_task.get_config.return_value,
        )

    @mock.patch('tron.mesos.MesosTask', autospec=True)
    def test_create_task(self, mock_task):
        cluster = MesosCluster('mesos-cluster-a.me')
        mock_serializer = mock.MagicMock()
        task = cluster.create_task(
            action_run_id='action_c',
            command='echo hi',
            cpus=1,
            mem=10,
            constraints=[],
            docker_image='container:latest',
            docker_parameters=[],
            env={'TESTING': 'true'},
            extra_volumes=[],
            serializer=mock_serializer,
        )
        cluster.runner.TASK_CONFIG_INTERFACE.assert_called_once_with(
            name='action_c',
            cmd='echo hi',
            cpus=1,
            mem=10,
            constraints=[],
            image='container:latest',
            docker_parameters=[],
            environment={'TESTING': 'true'},
            volumes=[],
            uris=[DOCKERCFG_LOCATION],
            offer_timeout=OFFER_TIMEOUT,
        )
        assert_equal(task, mock_task.return_value)
        mock_task.assert_called_once_with(
            'action_c',
            cluster.runner.TASK_CONFIG_INTERFACE.return_value,
            mock_serializer,
        )

    def test_process_event_task(self):
        event = mock_task_event('this_task', 'some_platform_type')
        cluster = MesosCluster('mesos-cluster-a.me')
        mock_task = mock.MagicMock(spec_set=MesosTask)
        mock_task.get_mesos_id.return_value = 'this_task'
        cluster.tasks['this_task'] = mock_task

        cluster._process_event(event)
        mock_task.handle_event.assert_called_once_with(event)

    def test_process_event_task_id_invalid(self):
        event = mock_task_event('other_task', 'some_platform_type')
        cluster = MesosCluster('mesos-cluster-a.me')
        mock_task = mock.MagicMock(spec_set=MesosTask)
        mock_task.get_mesos_id.return_value = 'this_task'
        cluster.tasks['this_task'] = mock_task

        cluster._process_event(event)
        assert_equal(mock_task.handle_event.call_count, 0)

    def test_process_event_control_stop(self):
        event = mock.MagicMock(
            kind='control',
            message='stop',
        )
        cluster = MesosCluster('mesos-cluster-a.me')
        cluster._process_event(event)
        assert_equal(cluster.runner.stop.call_count, 1)
        assert_equal(cluster.deferred.cancel.call_count, 1)
