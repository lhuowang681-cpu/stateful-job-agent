"""Current index messages on the existing Redis Stream transport primitives."""
from job_agent.backend_service.redis_streams import RedisStreamDispatchQueue
from job_agent.resume_workspace.index_dispatch import decode_delivery


class IndexStreamQueue(RedisStreamDispatchQueue):
    def __init__(self,redis_url,authority,*,max_entries=10000):
        if not 100<=max_entries<=100000:raise ValueError('index_stream_retention_invalid')
        super().__init__(redis_url,stream_name='job-agent:v3:'+authority,group_name='index-workers',
            client_parameters={'socket_timeout':2,'socket_connect_timeout':2})
        self.max_entries=max_entries;self.reclaim_cursor='0-0'

    def publish(self,event):
        fields={k:str(event[k]) for k in ('authority','event_id','task_id','generation')}
        return self._redis.xadd(self.stream_name,fields,maxlen=self.max_entries,approximate=True)

    _delivery=staticmethod(decode_delivery)

    def reclaim(self,*,consumer_name,min_idle_ms,count=10):
        response=self._redis.xautoclaim(self.stream_name,self.group_name,consumer_name,
            min_idle_ms,self.reclaim_cursor,count=count)
        self.reclaim_cursor=response[0]
        # Deleted pending IDs are handled by the PG reconciliation path, never
        # treated as successful business execution.
        return [decode_delivery(mid,fields) for mid,fields in response[1]]

    def monitoring(self):
        return {'lag':self.depth(),'pending':self.pending(),'retained_entries':self.retained_entries(),
            'configured_max_entries_approximate':self.max_entries,'reclaim_cursor':self.reclaim_cursor}
