import threading
from time import time as now


CREATED = '_pypool_created__'
RELEASED = '_pypool_released__'


class Pool(object):
    """
        Abstract thread-safe class for pooling reusable resources. You must
        override the create_resource method in child classes, and if needed you
        must also override the destroy_resource method.

        Obtain a resource from the pool by calling get_resource, and release the
        resource back into the pool by calling release_resource(resource).

        You can get the current status of the pool by calling get_status.
    """
    # class defaults
    count_cleared = 0
    count_created = 0
    count_killed_stale = 0
    count_killed_ttl = 0
    count_overflow_discard = 0
    count_served_from_pool = 0

    def __init__(self, pool_size_limit=10, max_age=3600, max_idle_time=300):
        # create the pool and the pool lock
        self.__pool = []
        self.__pool_lock = threading.Lock()
        self.pool_size_limit = pool_size_limit
        self.max_age = max_age
        self.max_idle_time = max_idle_time

    def create_resource(self):
        """
            Override this method in child classes to return a new
            instance of the pooled resource type.
        """
        return None

    def clear_pool(self, new_pool_size_limit=None):
        """
            def clear_pool(self, new_pool_size_limit=None):
            Clear the pool and destroy all the resources it contains,
            optionally setting a new pool size limit.
        """
        # lock the pool and swap in a new, empty one
        self.__pool_lock.acquire()
        try:
            old_pool = self.__pool
            self.__pool = []
            if new_pool_size_limit != None:
                self.pool_size_limit = new_pool_size_limit
        finally:
            self.__pool_lock.release()
        # free all the resources that were in the old pool
        self.count_cleared += len(old_pool)
        self.destroy_resources(old_pool)

    def destroy_resources(self, resource_list):
        """
            def destroy_resources(self, resource_list):
            Destroy the resources passed in resource_list.
        """
        for resource in resource_list:
            self.destroy_resource(resource)

    def destroy_resource(self, resource):
        """
            Override this method in child classes to destroy the
                resource instance passed in resource (if needed).
        """
        pass

    def get_resource(self):
        """
            def get_resource(self):
            Get a resource instance from the pool. If none are available
            one will be created by calling self.create_resource().
        """
        # snapshot the current moment in time and prepare to validate
        #   the age of the available resources
        now_time = now()
        min_fresh_time = \
                now_time - self.max_idle_time if self.max_idle_time \
                else 0
        min_created_time = \
                now_time - self.max_age if self.max_age \
                else 0
        kill_list = []
        while True:
            # get the oldest instance and remove it from the pool
            resource = self._pull()
            if not resource:
                break
            resdict = resource.__dict__
            # serve the resource if it is fresh enough, else kill it
            if resdict.get(CREATED, 0) < min_created_time:
                self.count_killed_ttl += 1
                kill_list.append(resource)
            elif resdict.get(RELEASED, 0) < min_fresh_time:
                self.count_killed_stale += 1
                kill_list.append(resource)
            else:
                self.count_served_from_pool += 1
                break
        # destroy resources in the kill list
        self.destroy_resources(kill_list)
        # if no resource was available in the pool then create a new one
        if not resource:
            resource = self.create_resource()
            # store this directly in the instance dict to bypass
            #   any class dunder machines (i.e. __setattr__)
            resource.__dict__[CREATED] = now()
            self.count_created += 1
        return resource

    def get_status(self):
        """
            def get_status(self):
            Returns a dictionary containing the current state of the pool.
            The following values are returned:
                pool_size (# of available resources in the pool)
                pool_size_limit (max resources allowed in the pool)
                count_created (vs count_served_from_pool)
                count_cleared (destroyed by calls to clear_pool)
                count_killed_stale (max_idle_time timeout)
                count_killed_ttl (max_age timeout)
                count_overflow_discard (exceeded pool_size_limit)
                count_served_from_pool (vs count_created)
        """
        return {
            "pool_size": len(self.__pool),
            "pool_size_limit": self.pool_size_limit,
            "count_created": self.count_created,
            "count_cleared": self.count_cleared,
            "count_killed_stale": self.count_killed_stale,
            "count_killed_ttl": self.count_killed_ttl,
            "count_overflow_discard": self.count_overflow_discard,
            "count_served_from_pool": self.count_served_from_pool,
            }

    def preheat(self, count):
        for res in [self.get_resource() for x in range(count)]:
            self.release_resource(res)

    def _pull(self):
        """
            def _pull(self):
            Pull the oldest resource instance from the pool and return it.
        """
        self.__pool_lock.acquire()
        try:
            return self.__pool.pop(0) if self.__pool else None
        finally:
            self.__pool_lock.release()

    def release_resource(self, resource):
        """
            def release_resource(self, resource):
            Release a resource instance back to the pool. If the pool is
            full the resource will be destroyed.
        """
        # lock the pool and store the resource
        self.__pool_lock.acquire()
        try:
            if (not self.pool_size_limit) or (len(self.__pool) < self.pool_size_limit):
                # store this directly in the instance dict to bypass
                #   any class dunder machines (i.e. __setattr__)
                resource.__dict__[RELEASED] = now()
                self.__pool.append(resource)
                stored = True
            else:
                stored = False
        finally:
            self.__pool_lock.release()
        if not stored:
            self.count_overflow_discard += 1
            self.destroy_resource(resource)

    def restart_pool(self, pool_size_limit):
        """
            def restart_pool(self, pool_size_limit):
            Destroy the current pool and all the resrouces it contains and
            create a new pool with pool_size_limit.
        """
        self.clear_pool(pool_size_limit)

    def shut_down(self):
        """
            def shut_down(self):
            Destroy the current pool and all the resrouces it contains.
            No new pool is created. All future get_resource calls will return
            new resource instances. All future release_resource calls will immediately
            destroy the released resource instances.
        """
        self.clear_pool(-1)
