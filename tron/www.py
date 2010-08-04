"""Management Web Services Interface

Got to know what's going on ?
"""
import logging

from twisted.internet import reactor

from twisted.cred import checkers
from twisted.web import server, resource, http

import simplejson

from tron.utils import timeutils

log = logging.getLogger("tron.www")

def respond(request, response_dict, code=http.OK, headers=None):
    """Helper to generate a json response"""
    request.setResponseCode(code)
    request.setHeader('content-type', 'text/json')
    if headers:
        for key, val in headers.iteritems():
            request.setHeader(key, val)
    if response_dict:
        return simplejson.dumps(response_dict)
    return ""

def job_run_state(job_run):
    if job_run.is_success:
        return "SUCC"
    if job_run.is_cancelled:
        return "CANC"
    if job_run.is_running:
        return "RUNN"
    if job_run.is_failed:
        return "FAIL"
    if job_run.is_scheduled:
        return "SCHE"
    if job_run.is_queued:
        return "QUE"
        
    return "UNKWN"

class ActionRunResource(resource.Resource):
    isLeaf = True
    def __init__(self, act_run):
        self._act_run = act_run
        resource.Resource.__init__(self)

    def render_GET(self, request):
        output = {
            'id': self._act_run.id, 
            'state': job_run_state(self._act_run),
            'node': self._act_run.node.hostname,
        }
        if request.args and request.args['num_lines'][0].isdigit():
            output['output'] = self._act_run.tail_output(int(request.args['num_lines'][0]))

        return respond(request, output)

    def render_POST(self, request):
        log.debug("Handling post request for action run %s", self._act_run.id)
        cmd = request.args['action'][0]
        if cmd == 'start':
            return self._start(request)
        elif cmd == 'succeed':
            return self._succeed(request)
        elif cmd == 'cancel':
            return self._cancel(request)
        elif cmd == 'fail':
            return self._fail(request)

        log.warning("Unknown request action %s", request.args['action'])
        request.setResponseCode(http.NOT_IMPLEMENTED)
    
    def _start(self, request):
        if not self._act_run.is_success and not self._act_run.is_running:
            log.info("Starting job run %s", self._act_run.id)
            self._act_run.start()
        else:
            log.warning("Request to start job run %s when it's already done", self._act_run.id)

        return respond(request, None, code=http.SEE_OTHER, headers={'Location': "/jobs/%s" % self._act_run.id.replace('.', '/')})

    def _succeed(self, request):
        if not self._act_run.is_running and not self._act_run.is_success:
            log.info("Marking job run %s for success", self._act_run.id)
            self._act_run.succeed()
        else:
            log.warning("Request to mark job run %s succeed when it has already", self._act_run.id)

        return respond(request, None, code=http.SEE_OTHER, headers={'location': "/jobs/%s" % self._act_run.id.replace('.', '/')})

    def _cancel(self, request):
        if self._act_run.is_scheduled or self._act_run.is_queued:
            log.info("Cancelling job %s", self._act_run.id)
            self._act_run.cancel()
        else:
            log.warning("Request to cancel job run %s when it's already cancelled", self._act_run.id)

        return respond(request, None, code=http.SEE_OTHER, headers={'location': "/jobs/%s" % self._act_run.id.replace('.', '/')})

    def _fail(self, request):
        if not self._act_run.is_running and not self._act_run.is_success and not self._act_run.is_failed:
            log.info("Marking job run %s as failed", self._act_run.id)
            self._act_run.fail(0)
        else:
            log.warning("Request to fail job run %s when it's already running or done", self._act_run.id)

        return respond(request, None, code=http.SEE_OTHER, headers={'location': "/jobs/%s" % self._act_run.id.replace('.', '/')})
        

class JobRunResource(resource.Resource):
    isLeaf = False
    def __init__(self, run):
        self._run = run
        resource.Resource.__init__(self)

    def getChild(self, act_name, request):
        if act_name == '':
            return self
        
        for act_run in self._run.runs:
            if act_name == act_run.action.name:
                return ActionRunResource(act_run)

        return resource.NoResource("Cannot find action '%s' for job run '%s'" % (act_name, self._run.id)) 

    def render_GET(self, request):
        run_output = []
        state = job_run_state(self._run)
        
        for action_run in self._run.runs:
            action_state = job_run_state(action_run)
            
            run_output.append({
                'id': action_run.id,
                'run_time': action_run.run_time and str(action_run.run_time),
                'start_time': action_run.start_time and str(action_run.start_time),
                'end_time': action_run.end_time and str(action_run.end_time),
                'exit_status': action_run.exit_status,
                'state': action_state,
            })

        output = {
            'runs': run_output, 
            'id': self._run.id, 
            'state': state,
            'node': self._run.node.hostname,
        }
        
        return respond(request, output)

    def render_POST(self, request):
        log.debug("Handling post request for run %s", self._run.id)
        cmd = request.args['action'][0]
        if cmd == "start":
            return self._start(request)
        elif cmd == "succeed":
            return self._succeed(request)
        elif cmd == "fail":
            return self._fail(request)
        elif cmd == "cancel":
            return self._cancel(request)
        
        log.warning("Unknown request action %s", request.args['action'])
        request.setResponseCode(http.NOT_IMPLEMENTED)

    def _start(self, request):
        if not self._run.is_success and not self._run.is_running:
            log.info("Starting job run %s", self._run.id)
            self._run.start()
        else:
            log.warning("Request to start job run %s when it's already done", self._run.id)

        return respond(request, None, code=http.SEE_OTHER, headers={'Location': "/jobs/%s" % self._run.id.replace('.', '/')})

    def _succeed(self, request):
        if not self._run.is_running and not self._run.is_success:
            log.info("Marking job run %s for success", self._run.id)
            self._run.succeed()
        else:
            log.warning("Request to mark job run %s succeed when it has already", self._run.id)

        return respond(request, None, code=http.SEE_OTHER, headers={'location': "/jobs/%s" % self._run.id.replace('.', '/')})

    def _cancel(self, request):
        if self._run.is_scheduled or self._run.is_queued:
            log.info("Cancelling job %s", self._run.id)
            self._run.cancel()
        else:
            log.warning("Request to cancel job run %s when it's already cancelled", self._run.id)

        return respond(request, None, code=http.SEE_OTHER, headers={'location': "/jobs/%s" % self._run.id.replace('.', '/')})

    def _fail(self, request):
        if not self._run.is_running and not self._run.is_success and not self._run.is_failed:
            log.info("Marking job run %s as failed", self._run.id)
            self._run.fail()
        else:
            log.warning("Request to fail job run %s when it's already running or done", self._run.id)

        return respond(request, None, code=http.SEE_OTHER, headers={'location': "/jobs/%s" % self._run.id.replace('.', '/')})

class JobResource(resource.Resource):
    """A resource that describes a particular job"""
    isLeaf = False
    def __init__(self, job):
        self._job = job
        resource.Resource.__init__(self)

    def getChild(self, run_num, request):
        if run_num == '':
            return self
        
        if run_num.isdigit():
            run = self._job.get_run_by_num(int(run_num))
            if run:
                return JobRunResource(run)
        
        return resource.NoResource("Cannot run number '%s' for job '%s'" % (run_num, self._job.name))

    def render_GET(self, request):
        run_output = []
        for job_run in self._job.runs:
            state = job_run_state(job_run)
                
            run_output.append({
                'id': job_run.id,
                'href': request.childLink(job_run.id),
                'run_time': job_run.run_time and str(job_run.run_time),
                'start_time': job_run.start_time and str(job_run.start_time),
                'end_time': job_run.end_time and str(job_run.end_time),
                'state': state,
            })

        resources_output = []
        
        output = {
            'name': self._job.name,
            'scheduler': str(self._job.scheduler),
            'runs': run_output,
            'action_names': map(lambda t: t.name, self._job.topo_actions),
            'node_pool': map(lambda n: n.hostname, self._job.node_pool.nodes),
        }
        return respond(request, output)

    def _queue(self, request):
        """Queue up a run for the current job"""
        # Let's see if there is already a queued run
        last_run = None
        if self._job.runs:
            last_run = self._job.runs[-1]

        if last_run and not last_run.is_done:
            if last_run.run_time >= timeutils.current_time():
                # There is a scheduled run, but it isn't time yet.
                # Set this run to start now!
                last_run.run_time = timeutils.current_time()

                log.info("Request to queue job %s rescheduling run %s", self._job.name, last_run.id)
            else:
                # There is already a run that is set to run now so there is nothing for us to do
                log.info("Request to queue job %s but we're already waiting on run %s", self._job.name, last_run.id)

            run_href = request.childLink(last_run.id)
            log.debug("Redirecting to %s", run_href)
            return respond(request, None, code=http.SEE_OTHER, headers={'Location': run_href})
                
        log.info("Creating new run for %s", self._job.name)
        new_run = self._job.build_run()
        new_run.run_time = timeutils.current_time()

        run_href = request.childLink(new_run.id)
        return respond(request, None, code=http.SEE_OTHER, headers={'Location': run_href})

    def render_POST(self, request):
        log.debug("Handling post request for %s", self._job.name)
        if request.args['action'][0] == "queue":
            return self._queue(request)
        log.warning("Unknown request action %s", request.args['action'])
        request.setResponseCode(http.NOT_IMPLEMENTED)
            

class JobsResource(resource.Resource):
    """Resource for all our daemon's jobs"""
    def __init__(self, master_control):
        self._master_control = master_control
        resource.Resource.__init__(self)


    def getChild(self, name, request):
        if name == '':
            return self
        
        found = self._master_control.jobs.get(name)
        if found is None:
            return resource.NoResource("Cannot  find job '%s'" % name)
        
        return JobResource(found)
        
    def render_GET(self, request):
        request.setHeader("content-type", "text/json")
        
        job_list = []
        for current_job in self._master_control.jobs.itervalues():
            last_success = None
            if current_job.runs:
                last_job = current_job.runs[-1]
                
                for job_run in reversed(current_job.runs):
                    if job_run.is_success:
                        last_success = str(job_run.end_time)
                        break

            job_desc = {
                'name': current_job.name,
                'href': request.childLink(current_job.name),
                'scheduler': str(current_job.scheduler),
                'last_success': last_success,
            }
            job_list.append(job_desc)

        output = {
            'jobs': job_list,
        }
        return respond(request, output)


class RootResource(resource.Resource):
    def __init__(self, master_control):
        self._master_control = master_control
        resource.Resource.__init__(self)
        
        # Setup children
        self.putChild('jobs', JobsResource(master_control))

    def getChild(self, name, request):
        if name == '':
            return self
        else:
            return resource.Resource.getChild(self, name, request)

    def render_GET(self, request):
        return respond(request, {'status': "I'm alive biatch"})

if __name__ == '__main__':
    from twisted.internet import reactor
    from testify.utils import turtle
    master_control = turtle.Turtle()
    master_control.jobs = {
        'test_job': turtle.Turtle(name="test_job", node=turtle.Turtle(hostname="batch0")),
    }
    reactor.listenTCP(8082, server.Site(RootResource(master_control)))
    reactor.run()
    
    
