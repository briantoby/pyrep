# standard distribution imports
from __future__ import print_function
import os, sys
import time
import uuid
import traceback
import warnings
import tarfile
import tempfile
import shutil
import inspect
from datetime import datetime
from functools import wraps
from pprint import pprint
import copy, json
try:
    import cPickle as pickle
except:
    import pickle

# import pylocker
from pylocker import Locker

# pyrep imports
from .__pkginfo__ import __version__

# python version dependant imports
if sys.version_info >= (3, 0):
    # This is python 3
    str        = str
    long       = int
    unicode    = str
    bytes      = bytes
    basestring = str
else:
    str        = str
    unicode    = unicode
    bytes      = str
    long       = long
    basestring = basestring

# set warnings filter to always
warnings.simplefilter('always')

def get_pickling_errors(obj, seen=None):
    """Investigate pickling errors."""
    if seen == None:
        seen = []
    if hasattr(obj, "__getstate__"):
        state = obj.__getstate__()
    else:
        return None
    if state == None:
        return 'object state is None'
    if isinstance(state,tuple):
        if not isinstance(state[0], dict):
            state=state[1]
        else:
            state=state[0].update(state[1])
    result = {}
    for i in state:
        try:
            pickle.dumps(state[i], protocol=2)
        except pickle.PicklingError as e:
            if not state[i] in seen:
                seen.append(state[i])
                result[i]=get_pickling_errors(state[i],seen)
    return result


def get_dump_method(dump):
    if dump is None:
        dump = 'pickle'
    if dump.startswith('pickle'):
        if dump == 'pickle':
            proto = 2
        else:
            proto = dump.strip('pickle')
            try:
                proto = int(proto)
                assert proto>=-1
            except:
                raise Exception("protocol must be an integer >=-1")
        code = """
try:
    import cPickle as pickle
except:
    import pickle
with open('$FILE_PATH', 'wb') as fd:
    pickle.dump( value, fd, protocol=%i )
"""%proto
    elif dump.startswith('dill'):
        if dump == 'dill':
            proto = 2
        else:
            proto = dump.strip('dill')
            try:
                proto = int(proto)
                assert proto>=-1
            except:
                raise Exception("protocol must be an integer >=-1")
        code = """
import dill
with open('$FILE_PATH', 'wb') as fd:
    dill.dump( value, fd, protocol=%i )
"""%proto
    elif dump == 'json':
        code = """
import json
with open('$FILE_PATH', 'w') as fd:
    json.dump( value,fd )
"""
    elif dump == 'numpy':
        code = """
import numpy
with open('$FILE_PATH', 'wb') as fd:
    numpy.save(file=fd, arr=value)
"""
    elif dump == 'numpy_text':
        code = """
import numpy
numpy.savetxt(fname='$FILE_PATH', X=value, fmt='%.6e')
"""
    else:
        assert isinstance(dump, basestring), "dump must be None or a string"
        assert '$FILE_PATH' in dump, "string dump code must inlcude '$FILE_PATH'"
        code = dump
    # return
    return code




def get_pull_method(pull):
    if pull is None or pull.startswith('pickle'):
        code = """
import os
try:
    import cPickle as pickle
except:
    import pickle
with open('$FILE_PATH', 'rb') as fd:
    PULLED_DATA = pickle.load( fd )
"""
    elif pull.startswith('dill'):
        code = """
import dill
with open('$FILE_PATH', 'rb') as fd:
    PULLED_DATA = dill.load( fd )
"""
    elif pull == 'json':
        code = """
import json
with open('$FILE_PATH', 'r') as fd:
    PULLED_DATA = json.load(fd)
"""
    elif pull == 'numpy':
        code = """
import numpy
with open('$FILE_PATH', 'rb') as fd:
    PULLED_DATA=numpy.load(file=fd)

"""
    elif pull == 'numpy_text':
        code = """
import numpy
with open('$FILE_PATH', 'r') as fd:
    PULLED_DATA=numpy.loadtxt(fname=fd)
"""
    else:
        assert isinstance(pull, basestring), "pull must be None or a string"
        assert 'PULLED_DATA' in pull, "string pull code must inlcude 'PULLED_DATA'"
        assert '$FILE_PATH' in pull, "string pull code must inlcude '$FILE_PATH'"
        code = pull
    # return
    return code





def path_required(func):
    """Decorate methods when repository path is required."""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        if self.path is None:
            warnings.warn('Must load or initialize the repository first !')
            return
        return func(self, *args, **kwargs)
    return wrapper


class Repository(object):
    """
    This is a pythonic way to organize dumping and pulling python objects
    or any type of files to a folder or directory that we call repository.
    Any directory can be a repository, it suffices to initialize a Repository
    instance in a directory to start dumping and pulling object into it.
    Any directory that has .pyreprepo binary file in it is theoretically a
    pyrep Repository.

    :Parameters:
        #. repo (None, path, Repository): This is used to initialize a Repository instance.\n
           If None, Repository is initialized but not assigned to any directory.\n
           If Path, Repository is loaded from directory path unless directory is not a repository and error will be raised.\n
           If Repository, current instance will cast the given Repository instance.
    """
    def __init__(self, path=None):
        self.__repoLock  = '.pyreplock'
        self.__repoFile  = '.pyreprepo'
        self.__dirInfo   = '.pyrepdirinfo'
        self.__dirLock   = '.pyrepdirlock'
        self.__fileInfo  = '.%s_pyrepfileinfo'  # %s replaces file name
        self.__fileClass = '.%s_pyrepfileclass'  # %s replaces file name
        self.__fileLock  = '.%s_pyrepfilelock'  # %s replaces file name
        #self.__objectDir = '.%s_pyrepobjectdir' # %s replaces file name
        # initialize repository
        self.reset()
        # if path is not None, load existing repository
        if path is not None:
            assert self.is_repository(path), "given path is not a repository. use create_repository or give a valid repository path"
            self.load_repository(repo)

    def __str__(self):
        if self.__path is None:
            return ""
        string = os.path.normpath(self.__path)
        reprSt = self.get_repository_state()
        # walk files
        leftAdjust = "  "
        for fdict in reprSt:
            fdname = list(fdict)[0]
            if fdname == '':
                continue
            if fdict[fdname].get('pyrepfileinfo', False):
                string += "\n"
                string += leftAdjust
                string += os.path.basename(fdname)
            elif fdict[fdname].get('pyrepdirinfo', False):
                splitPath = fdname.split(os.sep)
                leftAdjust = ''.join(['  '*(len(item)>0) for item in splitPath])
                string += "\n"
                string += leftAdjust
                string += os.sep+str(splitPath[-1])
            else:
                raise Exception('Not sure what to do next. Please report issue')
        return string

    def __repr__(self):
        repr = "pyrep "+self.__class__.__name__+" (Version "+str(self.__repo['pyrep_version'])+")"
        if self.__path is None:
            return repr
        nfiles = 0
        ndirs  = 0
        for fdict in self.get_repository_state():
            fdname = list(fdict)[0]
            if fdname == '':
                continue
            if fdict[fdname].get('pyrepfileinfo', False):
                nfiles += 1
            elif fdict[fdname].get('pyrepdirinfo', False):
                ndirs += 1
            else:
                raise Exception('Not sure what to do next. Please report issue')
        repr += " @%s [%i files] [%i directories]"%(self.__path, nfiles, ndirs)
        return repr



    def __sync_files(self, repoPath, dirs):
        errors  = []
        synched = []
        def _walk_dir(relPath, relDirList, relSynchedList):
            if not os.path.isdir(os.path.join(repoPath, relPath)):
                errors.append("Repository directory '%s' not found on disk"%relPath)
            else:
                for k in relDirList:
                    if isinstance(k, dict):
                        if len(k)!=1:
                            errors.append("Repository directory found in '%s' info dict length is not 1"%relPath)
                            continue
                        dn = list(k)[0]
                        if not isinstance(dn, basestring):
                            errors.append("Repository directory found in '%s' info dict key is not a string"%relPath)
                            continue
                        if not len(dn):
                            errors.append("Repository directory found in '%s' info dict key is an empty string"%relPath)
                            continue
                        rp = os.path.join(repoPath, relPath, dn)
                        rsd = {dn:[]}
                        relSynchedList.append(rsd)
                        _walk_dir(relPath=rp, relDirList=k[dn], relSynchedList=rsd[dn])
                        if not len(rsd[dn]):
                            _ = relSynchedList.pop( relSynchedList.index(rsd) )
                    elif isinstance(k, basestring):
                        relFilePath = os.path.join(repoPath, relPath, k)
                        relInfoPath = os.path.join(repoPath, relPath, self.__fileInfo%k)
                        if not os.path.isfile(relFilePath):
                            errors.append("Repository file '%s' not found on disk"%relFilePath)
                            continue
                        elif not os.path.isfile(relInfoPath):
                            errors.append("Repository file info file '%s' not found on disk"%relFilePath)
                            continue
                        relSynchedList.append(k)
                    else:
                        errors.append("Repository file found in '%s' info dict key is not a string"%relPath)
                        continue
        # call recursive _walk_dir
        _walk_dir(relPath='', relDirList=dirs, relSynchedList=synched)
        return synched, errors

    def __save_dirinfo(self, info, dirInfoPath, create=False):
        # create main directory info file
        oldInfo = None
        if info is None and os.path.isfile(dirInfoPath):
            with open(dirInfoPath, 'r') as fd:
                oldInfo = json.load(fd)
            if self.__repo['repository_unique_name'] != oldInfo['repository_unique_name']:
                info = ''
        if info is None and create:
            info = ''
        if info is not None:
            if os.path.isfile(dirInfoPath):
                if oldInfo is None:
                    with open(dirInfoPath, 'r') as fd:
                        oldInfo = json.load(fd)
                if self.__repo['repository_unique_name'] != oldInfo['repository_unique_name']:
                    createTime = lastUpdateTime = time.time()
                else:
                    createTime     = oldInfo['create_utctime']
                    lastUpdateTime = time.time()
            else:
                createTime = lastUpdateTime = time.time()
            info = {'repository_unique_name':self.__repo['repository_unique_name'],
                    'create_utctime':createTime,
                    'last_update_utctime':lastUpdateTime,
                    'info':info}
            with open(dirInfoPath, 'w') as fd:
                json.dump( info,fd )



    def __clean_before_after(self, stateBefore, stateAfter, keepNoneEmptyDirectory=True):
        """clean repository given before and after states"""
        # prepare after for faster search
        errors    = []
        afterDict = {}
        [afterDict.setdefault(list(aitem)[0],[]).append(aitem) for aitem in stateAfter]
        # loop before
        for bitem in reversed(stateBefore):
            relaPath = list(bitem)[0]
            basename = os.path.basename(relaPath)
            btype    = bitem[relaPath]['type']
            alist    = afterDict.get(relaPath, [])
            aitem    = [a for a in alist if a[relaPath]['type']==btype]
            if len(aitem)>1:
                errors.append("Multiple '%s' of type '%s' where found in '%s', this should never had happened. Please report issue"%(basename,btype,relaPath))
                continue
            if not len(aitem):
                removeDirs  = []
                removeFiles = []
                if btype == 'dir':
                    if not len(relaPath):
                        errors.append("Removing main repository directory is not allowed")
                        continue
                    removeDirs.append(os.path.join(self.__path,relaPath))
                    removeFiles.append(os.path.join(self.__path,relaPath,self.__dirInfo))
                    removeFiles.append(os.path.join(self.__path,relaPath,self.__dirLock))
                elif btype == 'file':
                    removeFiles.append(os.path.join(self.__path,relaPath))
                    removeFiles.append(os.path.join(self.__path,relaPath,self.__fileInfo%basename))
                    removeFiles.append(os.path.join(self.__path,relaPath,self.__fileLock%basename))
                else:
                    ### MUST VERIFY THAT ONCE pyrepobjectdir IS IMPLEMENTED
                    removeDirs.append(os.path.join(self.__path,relaPath))
                    removeFiles.append(os.path.join(self.__path,relaPath,self.__fileInfo%basename))
                # remove files
                for fpath in removeFiles:
                    if os.path.isfile(fpath):
                        try:
                            os.remove(fpath)
                        except Exception as err:
                            errors.append("Unable to clean file '%s' (%s)"%(fpath, str(err)))
                # remove directories
                for dpath in removeDirs:
                    if os.path.isdir(dpath):
                        if keepNoneEmptyDirectory or not len(os.listdir(dpath)):
                            try:
                                shutil.rmtree(dpath)
                            except Exception as err:
                                errors.append("Unable to clean directory '%s' (%s)"%(fpath, str(err)))
        # return result and errors list
        return len(errors)==0, errors

    def __set_repository_directory(self, relativePath, dirList):
        splitted = self.to_repo_relative_path(path=relativePath, split=True)
        if splitted == ['']:
            self.__repo['walk_repo'] = dirList
            return True, ""
        error = None
        cDir  = self.__repo['walk_repo']
        for idx, dirname in enumerate(splitted):
            dList = [d for d in cDir if isinstance(d, dict)]
            if not len(dList):
                cDir = None
                error = "Repository relative directory '%s' not found"%os.sep.join(splitted[:idx])
                break
            cDict = [d for d in dList if dirname in d]
            if not len(cDict):
                cDir = None
                error = "Repository relative directory '%s' not found"%os.sep.join(splitted[:idx])
                break
            if idx == len(splitted)-1:
                cDict[0][dirname] = dirList
            else:
                cDir = cDict[0][dirname]
        # return
        return False, error

    def __get_repository_parent_directory(self, relativePath):
        relativePath = self.to_repo_relative_path(path=relativePath, split=False)
        if relativePath == '':
            return None
        parentPath = os.path.dirname(relativePath)
        return self.__get_repository_directory(relativePath=parentPath)

    def __get_repository_directory(self, relativePath):
        cDir = self.__repo['walk_repo']
        splitted = self.to_repo_relative_path(path=relativePath, split=True)
        if splitted == ['']:
            return cDir
        for dirname in splitted:
            dList = [d for d in cDir if isinstance(d, dict)]
            if not len(dList):
                cDir = None
                break
            cDict = [d for d in dList if dirname in d]
            if not len(cDict):
                cDir = None
                break
            cDir = cDict[0][dirname]
        # return
        return cDir

    def __load_repository(self, path, verbose=True):
        # try to open
        if path.strip() in ('','.'):
            path = os.getcwd()
        repoPath = os.path.realpath( os.path.expanduser(path) )
        if not self.is_repository(repoPath):
            raise Exception("No repository found in '%s'"%str(repoPath))
        # get pyreprepo path
        repoInfoPath = os.path.join(repoPath, self.__repoFile)
        try:
            fd = open(repoInfoPath, 'rb')
        except Exception as e:
            raise Exception("Unable to open repository file(%s)"%e)
        # before doing anything try to lock repository
        # always create new locker, this makes the repository process and thread safe
        L =  Locker(filePath=None, lockPass=str(uuid.uuid1()), lockPath=os.path.join(repoPath, self.__repoLock))
        acquired, code = L.acquire_lock()
        # check if acquired.
        if not acquired:
            warnings.warn("code %s. Unable to aquire the lock when calling 'load_repository'. You may try again!"%(code,) )
            return
        try:
            # unpickle file
            try:
                repo = json.load( fd )
            except Exception as err:
                fd.close()
                raise Exception("Unable to load json repository (%s)"%str(err))
            finally:
                fd.close()
            # check if it's a pyreprepo instance
            assert isinstance(repo, dict), "pyrep repo must be a dictionary"
            assert "create_utctime" in repo, "'create_utctime' must be a key in pyrep repo dict"
            assert "last_update_utctime" in repo, "'last_update_utctime' must be a key in pyrep repo dict"
            assert "pyrep_version" in repo, "'pyrep_version' must be a key in pyrep repo dict"
            assert "walk_repo" in repo, "'walk_repo' must be a key in pyrep repo dict"
            assert isinstance(repo['walk_repo'], list), "pyrep info 'walk_repo' key value must be a list"
            # get paths dict
            repoFiles, errors = self.__sync_files(repoPath=repoPath, dirs=repo['walk_repo'])
            if len(errors) and verbose:
                warnings.warn("\n".join(errors))
            self.reset()
            self.__path = repoPath
            self.__repo['repository_unique_name'] = repo['repository_unique_name']
            self.__repo['repository_description'] = repo['repository_description']
            self.__repo['create_utctime']         = repo['create_utctime']
            self.__repo['last_update_utctime']    = repo['last_update_utctime']
            self.__repo['walk_repo']              = repoFiles
        except Exception as e:
            L.release_lock()
            raise Exception(e)
        finally:
            L.release_lock()


    @property
    def path(self):
        """The repository instance path which points to the directory where
        .pyreprepo is."""
        return self.__path

    @property
    def uniqueName(self):
        """Get repository unique name"""
        return self.__repo['repository_unique_name']

    def reset(self):
        #self.__locker = Locker(filePath=None, lockPass=str(uuid.uuid1()),lockPath='.pyreplock')
        self.__path   = None
        self.__repo   = {'repository_unique_name': str(uuid.uuid1()),
                         'create_utctime': time.time(),
                         'last_update_utctime': None,
                         'pyrep_version': str(__version__),
                         'repository_description': '',
                         'walk_repo': []}


    def is_repository(self, path):
        """
        Check if there is a Repository in path.

        :Parameters:
            #. path (string): The real path of the directory where to check if there is a repository.

        :Returns:
            #. result (boolean): Whether its a repository or not.
        """
        if path.strip() in ('','.'):
            path = os.getcwd()
        repoPath = os.path.realpath( os.path.expanduser(path) )
        return os.path.isfile( os.path.join(repoPath,self.__repoFile) )

    def load_repository(self, path, verbose=True):
        """
        Load repository from a directory path and update the current instance.

        :Parameters:
            #. path (string): The path of the directory from where to load the repository.
               If '.' or an empty string is passed, the current working directory will be used.
            #. verbose (boolean): Whether to be verbose about abnormalities

        :Returns:
             #. repository (pyrep.Repository): returns self repository with loaded data.
        """
        try:
            self.__load_repository(path=path, verbose=True)
        except Exception as err1:
            from .OldRepository import Repository
            REP=Repository()
            try:
                REP.load_repository(PATH)
            except Exception as err2:
                raise Exception("Unable to load repository (%s) (%s)"%(err1, err2))
            else:
                warnings.warn("This is an old repository version 2.x.y! Make sure to start using repositories 3.x.y ")
                return REP
        else:
            return self

    def create_repository(self, path, description=None, info=None, replace=True):
        """
        create a repository in a directory.
        This method insures the creation of the directory in the system if it is missing.\n

        **N.B. This method erases existing pyrep repository in the path but not the repository files.**

        :Parameters:
            #. path (string): The real absolute path where to create the Repository.
               If '.' or an empty string is passed, the current working directory will be used.
            #. description (None, str): Repository description.
            #. info (None, str): Repository main directory information.
            #. replace (boolean): Whether to replace existing repository.

        :Returns:
            #. success (boolean): Whether creating repository was successful
            #. message (None, str): Any returned message.
        """
        assert isinstance(replace, bool), "replace must be boolean"
        assert isinstance(path, basestring), "path must be string"
        if info is None:
            info = ''
        assert isinstance(info, basestring), "info must be None or a string"
        if description is None:
            description = ''
        assert isinstance(description, basestring), "description must be None or a string"
        # get real path
        if path.strip() in ('','.'):
            path = os.getcwd()
        realPath = os.path.realpath( os.path.expanduser(path) )
        # reset if replace is set to True
        message = None
        if self.is_repository(realPath):
            if not replace:
                message = "A pyrep Repository already exists in the given path '%s' set replace to True if you need to proceed."%path
                return False, message
            else:
                message = "Old existing pyrep repository existing in the given path '%s' has been replaced."%path
                try:
                    for _df in os.listdir(realPath):
                        _p = os.path.join(realPath, _df)
                        if os.path.isdir(_p):
                            shutil.rmtree( _p )
                        else:
                            os.remove(_p)
                except Exception as err:
                    message = "Unable to clean remove repository before create (%s)"%(str(err))
                    return False, message
        if not os.path.isdir(realPath):
            os.makedirs(realPath)
        elif len(os.listdir(realPath)):
            return False, "Not allowed to create repository in a non empty directory"
        # reset repository
        oldRepo = self.__repo
        self.reset()
        self.__path = realPath.rstrip(os.sep)
        self.__repo['repository_description'] = description
        # save repository
        saved = self.save(info=info)
        if not saved:
            self.__repo = oldRepo
            message = "Absolute path and directories might be created but no pyrep Repository is created."
            return False, message
        # return
        return True, message


    @path_required
    def save(self, info=None):
        """ Save repository '.pyreprepo' to disk and create (if missing) or
         update (if info is not None) '.pyrepdirinfo'.

        :Parameters:
            #. info (None, str): Repository main directory information. If given
               will be replaced.

        :Returns:
            # success (bool): Whether saving was successful.
            # error (None, string): Fail to save repository message in case
              saving is not successful. If success is True, error will be None.
        """
        # get info
        if info is not None:
            assert isinstance(info, basestring), "info must be None or a string"
        dirInfoPath = os.path.join(self.__path, self.__dirInfo)
        if info is None and not os.path.isfile(dirInfoPath):
            info = ''
        # create and acquire lock
        L =  Locker(filePath=None, lockPass=str(uuid.uuid1()), lockPath=os.path.join(self.__path, self.__repoLock))
        acquired, code = L.acquire_lock()
        # check if acquired.
        if not acquired:
            return False, "code %s. Unable to aquire the lock when calling 'save'. You may try again!"%(code,)
        # open file
        repoInfoPath = os.path.join(self.__path, self.__repoFile)
        try:
            self.__save_dirinfo(info=info, dirInfoPath=dirInfoPath)
            # create repository
            with open(repoInfoPath, 'w') as fd:
                self.__repo["last_update_utctime"] = time.time()
                json.dump( self.__repo,fd )
        except Exception as err:
            L.release_lock()
            return False, "Unable to save repository (%s)"%err
        finally:
            L.release_lock()
            return True, None

    def is_name_allowed(self, path):
        """
        Get whether creating a file or a directory from the basenane of the given
        path is allowed

        :Parameters:
            #. path (str): The absolute or relative path or simply the file
               or directory name.

        :Returns:
            #. allowed (bool): Whether name is allowed.
            #. message (None, str): Reason for the name to be forbidden.
        """
        assert isinstance(path, basestring), "given path must be a string"
        name = os.path.basename(path)
        if not len(name):
            return False, "empty name is not allowed"
        # exact match
        for em in [self.__repoLock,self.__repoFile,self.__dirInfo,self.__dirLock]:
            if name == em:
                return False, "name '%s' is reserved for pyrep internal usage"%em
        # pattern match
        for pm in [self.__fileInfo,self.__fileLock]:#,self.__objectDir]:
            if name == pm or (name.endswith(pm[3:]) and name.startswith('.')):
                return False, "name pattern '%s' is not allowed as result may be reserved for pyrep internal usage"%pm
        # name is ok
        return True, None

    def to_repo_relative_path(self, path, split=False):
        """
        Given an absolute path, return relative path to diretory

        :Parameters:
            #. path (str): Path as a string
            #. split (boolean): Whether to split path to its components

        :Returns:
            #. relativePath (str, list): Relative path as a string or as a list
               of components if split is True
        """
        path = os.path.normpath(path)
        if path == '.':
            path = ''
        path = path.split(self.__path)[-1].strip(os.sep)
        #path = path.strip(os.sep).split(self.__path)[-1]
        if split:
            return path.split(os.sep)
        else:
            return path

    @path_required
    def get_repository_state(self, relaPath=None):
        """
        Get a list representation of repository state along with useful
        information. List state is ordered in levels


        :Parameters:
            #. relaPath (None, str): relative directory path from where to
               start. If None all repository representation is returned.

        :Returns:
            #. state (list): List representation of the repository.
               List items are all dictionaries. Every dictionary has a single
               key which is the file or the directory name and the value is a
               dictionary of information including:

                   * 'type': the type of the tracked whether it's file, dir, or objectdir
                   * 'exists': whether file or directory actually exists on disk
                   * 'pyrepfileinfo': In case of a file or an objectdir whether .%s_pyrepfileinfo exists
                   * 'pyrepdirinfo': In case of a directory whether .pyrepdirinfo exists
        """
        state = []
        def _walk_dir(relaPath, dirList):
            dirDict = {'type':'dir',
                       'exists':os.path.isdir(os.path.join(self.__path,relaPath)),
                       'pyrepdirinfo':os.path.isfile(os.path.join(self.__path,relaPath,self.__dirInfo)),
                      }
            state.append({relaPath:dirDict})
            # loop files and dirobjects
            for fname in sorted([f for f in dirList if isinstance(f, basestring)]):
                relaFilePath = os.path.join(relaPath,fname)
                realFilePath = os.path.join(self.__path,relaFilePath)
                #if os.path.isdir(realFilePath) and df.startswith('.') and df.endswith(self.__objectDir[3:]):
                #    fileDict = {'type':'objectdir',
                #                'exists':True,
                #                'pyrepfileinfo':os.path.isfile(os.path.join(self.__path,relaPath,self.__fileInfo%fname)),
                #               }
                #else:
                #    fileDict = {'type':'file',
                #                'exists':os.path.isfile(realFilePath),
                #                'pyrepfileinfo':os.path.isfile(os.path.join(self.__path,relaPath,self.__fileInfo%fname)),
                #               }
                fileDict = {'type':'file',
                            'exists':os.path.isfile(realFilePath),
                            'pyrepfileinfo':os.path.isfile(os.path.join(self.__path,relaPath,self.__fileInfo%fname)),
                           }
                state.append({relaFilePath:fileDict})
            # loop directories
            for ddict in sorted([d for d in dirList if isinstance(d, dict)], key=lambda k: list(k)[0]):
                dirname = list(ddict)[0]
                _walk_dir(relaPath=os.path.join(relaPath,dirname), dirList=ddict[dirname])
        # call recursive _walk_dir
        if relaPath is None:
            _walk_dir(relaPath='', dirList=self.__repo['walk_repo'])
        else:
            assert isinstance(relaPath, basestring), "relaPath must be None or a str"
            relaPath = self.to_repo_relative_path(path=relaPath, split=False)
            spath    = relaPath.split(os.sep)
            dirList=self.__repo['walk_repo']
            while len(spath):
                dirname = spath.pop(0)
                dList = [d for d in dirList if isinstance(d, dict)]
                if not len(dList):
                    dirList = None
                    break
                cDict = [d for d in dList if dirname in d]
                if not len(cDict):
                    dirList = None
                    break
                dirList = cDict[0][dirname]
            if dirList is not None:
                _walk_dir(relaPath=relaPath, dirList=dirList)
        # return state list
        return state

    def get_repository_directory(self, relativePath):
        """
        Get repository directory list.

        :Parameters:
            #. relativePath (string): The relative to the repository path .

        :Returns:
            #. dirList (None, list): List of directories and files in repository
               directory. If directory is not tracked in repository None is
               returned
        """
        return copy.deepcopy(self.__get_repository_directory(relativePath))

    def is_repository_directory(self, relativePath):
        """
        Get whether directory is registered in repository.

        :Parameters:
            #. relativePath (string): The relative to the repository path.

        :Returns:
            #. result (boolean): Whether directory is tracked and registered.
        """
        return self.__get_repository_directory(relativePath) is not None


    def is_repository_file(self, relativePath):
        """
        Check whether a given relative path is a repository file path

        :Parameters:
            #. relativePath (string): File relative path

        :Returns:
            #. isRepoFile (boolean): Whether file is a repository file.
            #. isFileOnDisk (boolean): Whether file is found on disk.
            #. isFileInfoOnDisk (boolean): Whether file info is found on disk
            #. isFileClassOnDisk (boolean): Whether file class is found on disk.
        """
        relativePath  = self.to_repo_relative_path(path=relativePath, split=False)
        if relativePath == '':
            return False, False, False, False
        relaDir, name = os.path.split(relativePath)
        fileOnDisk  = os.path.isfile(os.path.join(self.__path, relativePath))
        infoOnDisk  = os.path.isfile(os.path.join(self.__path,os.path.dirname(relativePath),self.__fileInfo%name))
        classOnDisk = os.path.isfile(os.path.join(self.__path,os.path.dirname(relativePath),self.__fileClass%name))
        cDir = self.__repo['walk_repo']
        if len(relaDir):
            for dirname in relaDir.split(os.sep):
                dList = [d for d in cDir if isinstance(d, dict)]
                if not len(dList):
                    cDir = None
                    break
                cDict = [d for d in dList if dirname in d]
                if not len(cDict):
                    cDir = None
                    break
                cDir = cDict[0][dirname]
        if cDir is None:
            return False, fileOnDisk, infoOnDisk, classOnDisk
        if name not in cDir:
            return False, fileOnDisk, infoOnDisk, classOnDisk
        # this is a repository registered file. check whether all is on disk
        return True, fileOnDisk, infoOnDisk, classOnDisk


    #@path_required
    #def maintain_directory(self, relativePath, keep=None, clean=True):
    #    """
    #    Maintain repository directory by keeping files and directories tracked
    #    and removing non tracked files and directories from system.
#
    #    :Parameters:
    #        #. relativePath (string): The relative to the repository path.
    #        #. keep (None, list, tuple, str): the list of tracked files
    #           (str) and directories (tuple) to keep in pyrep repository.
    #           If keep is None, then all files and directories in replaced
    #           directory will be transfered to newly created and tracked
    #           directory.
    #        #. clean (boolean): Whether to os remove any not tracked file or
    #           directory from given relative path.
#
    #    :Returns:
    #        #. success (boolean): Whether maintenance was successful.
    #        #. reason (None, string): Reason why maintenance was not successful.
    #    """
    #    assert isinstance(clean, bool), "clean must be boolean"
    #    assert isinstance(relativePath, str), "relativePath must be a string"
    #    assert clean or keep is not None, "keep must be not None or clean must be True"
    #    if keep is not None:
    #        if isinstance(keep, (str, tuple)):
    #            keep = [keep]
    #        assert isinstance(keep, (list)), "keep must be None a string or a list"
    #        assert all([isinstance(i,(str, tuple)) for i in keep]), "keep list items must be string or tuples"
    #        assert all([len(t)==1 for t in keep if isinstance(t,tuple)]), "keep list tuple items must be of length 1"
    #        assert all([isinstance(t[0], str) for t in keep if isinstance(t,tuple)]), "keep list tuple items unique value must be a string"
    #        keep = set(keep)
    #    # normalise path
    #    relativePath = self.to_repo_relative_path(path=relativePath, split=False)
    #    realPath     = os.path.join(self.__path,relativePath)
    #    error        = None
    #    mustSave     = False
    #    # keep
    #    L =  Locker(filePath=None, lockPass=str(uuid.uuid1()), lockPath=os.path.join(realPath, self.__dirLock))
    #    acquired, code = L.acquire_lock()
    #    if not acquired:
    #        error = "Code %s. Unable to aquire the lock when adding '%s'. All prior directories were added. You may try again, to finish adding directory"%(code,realPath)
    #        return False, error
    #    try:
    #        posList = self.get_repository_directory(relativePath=relativePath)
    #        assert posList is not None, "Unkown relative directory %s"%relativePath
    #        if keep is not None:
    #            _files     = [f for f in posList if isinstance(f, str)]
    #            _dirs      = [f for f in posList if isinstance(f, dict)]
    #            _keepFiles = [k for k in keep if isinstance(k,str)]
    #            _keepDirs  = [k[0] for k in keep if isinstance(k,tuple)]
    #            _keeping   = [f for f in _files if f in _keepFiles]
    #            _keeping.extend( [f for f in _dirs if list(f)[0] in _keepDirs] )
    #            if len(_keeping)!=len(posList):
    #                #self.__set_repository_directory(relativePath, posList)
    #                _ = [posList.pop(0) for _ in range(len(posList))]
    #                posList.extend(_keeping)
    #                mustSave = True
    #    except Exception as err:
    #        error = "Unable to maintan keeping files and directories (%s)"%(str(err),)
    #    finally:
    #        L.release_lock()
    #    # clean
    #    if clean and error is None:
    #        _keepFiles = [f for f in posList if isinstance(f, str)]
    #        _flocks    = [self.__fileLock%f for f in _keepFiles]
    #        _finfos    = [self.__fileInfo%f for f in _keepFiles]
    #        _keepFiles.extend(_flocks)
    #        _keepFiles.extend(_finfos)
    #        _keepFiles.extend([self.__repoLock,self.__repoFile,self.__dirInfo,self.__dirLock])
    #        _keepDirs  = [list(f)[0] for f in posList if isinstance(f, dict)]
    #        _keepDirs.extend([self.__objectDir%d for d in _keepDirs])
    #        for df in os.listdir(realPath):
    #            dfpath = os.path.join(realPath, df)
    #            if os.path.isdir(dfpath):
    #                if df not in _keepDirs:
    #                    try:
    #                        shutil.rmtree( dfpath )
    #                    except Exception as err:
    #                        error = "Unable to clean repository directory '%s' along with all it's contents (%s)"%(df,str(err))
    #                        break
    #            elif df not in _keepFiles:
    #                try:
    #                    os.remove(dfpath)
    #                except Exception as err:
    #                    error = "Unable to clean repository file '%s' (%s)"%(df,str(err))
    #                    break
    #    elif clean and error is not None:
    #        error += " --> Unable to clean files from disk"
    #    if mustSave:
    #        if error is not None:
    #            error += " --> Unable to save repository from disk"
    #        else:
    #            _, error = self.save()
    #    # return
    #    return error is None, error


    @path_required
    def add_directory(self, relativePath, info=None, clean=False):
        """
        Add a directory in the repository and creates its
        attribute in the Repository with utc timestamp.
        It insures adding all the missing directories in the path.

        :Parameters:
            #. relativePath (string): The relative to the repository path of the
               directory to add in the repository.
            #. info (None, string): Any random info about the added directory.
            #. clean (boolean): Whether to remove existing non repository
               tracked files and folders in all created directory chain tree.

        :Returns:
            #. success (boolean): Whether adding the directory was successful.
            #. message (None, string): Reason why directory was not added or
               random information.
        """
        assert isinstance(relativePath, basestring), "relativePath must be a string"
        if info is not None:
            assert isinstance(info, basestring), "info must be None or a string"
        # normalise path
        path = self.to_repo_relative_path(path=relativePath, split=False)
        # whether to replace
        if self.is_repository_directory(path):
            return True, "Directory is already tracked in repository"
        # check whether name is allowed
        allowed, reason = self.is_name_allowed(path)
        if not allowed:
            return False, reason
        # create directories
        error   = None
        posList = self.__repo['walk_repo']
        dirPath = self.__path
        spath   = path.split(os.sep)
        #print(path)
        for idx, name in enumerate(spath):
            # create and acquire lock.
            L =  Locker(filePath=None, lockPass=str(uuid.uuid1()), lockPath=os.path.join(dirPath, self.__dirLock))
            acquired, code = L.acquire_lock()
            if not acquired:
                error = "Code %s. Unable to aquire the lock when adding '%s'. All prior directories were added. You may try again, to finish adding directory"%(code,dirPath)
                break
            # add to directory
            try:
                dirPath = os.path.join(dirPath, name)
                riPath  = os.path.join(dirPath, self.__dirInfo)
                dList   = [d for d in posList if isinstance(d, dict)]
                dList   = [d for d in dList if name in d]
                # clean directory
                if not len(dList) and clean and os.path.exists(dirPath):
                    try:
                        shutil.rmtree( dirPath, ignore_errors=True )
                    except Exception as err:
                        error = "Unable to clean directory '%s' (%s)"%(dirPath, err)
                        break
                # create directory
                if not os.path.exists(dirPath):
                    try:
                        os.mkdir(dirPath)
                    except Exception as err:
                        error = "Unable to create directory '%s' (%s)"%(dirPath, err)
                        break
                # create and dump dirinfo
                self.__save_dirinfo(info=[None, info][idx==len(spath)-1],
                                    dirInfoPath=riPath, create=True)
                # update directory list
                if not len(dList):
                    rsd = {name:[]}
                    posList.append(rsd)
                    posList = rsd[name]
                else:
                    assert len(dList) == 1, "Same directory name dict is found twice. This should'n have happened. Report issue"
                    posList = dList[0][name]
            except Exception as err:
                error = "Unable to create directory '%s' info file (%s)"%(dirPath, str(err))
            finally:
                L.release_lock()
            if error is not None:
                break
        # save
        if error is None:
            _, error = self.save()
        # return
        return error is None, error

    def get_repository_parent_directory(self, relativePath):
        """
        """
        return copy.deepcopy(self.__get_repository_parent_directory(relativePath))

    @path_required
    def remove_directory(self, relativePath, clean=False):
        """
        Remove directory from repository tracking.

        :Parameters:
            #. relativePath (string): The relative to the repository path of the
               directory to remove from the repository.
            #. clean (boolean): Whether to os remove directory. If False only
               tracked files will be removed along with left empty directories.

        :Returns:
            #. success (boolean): Whether removing the directory was successful.
            #. reason (None, string): Reason why directory was not removed.
        """
        assert isinstance(clean, bool), "clean must be boolean"
        # normalise path
        relativePath = self.to_repo_relative_path(path=relativePath, split=False)
        parentPath, dirName = os.path.split(relativePath)
        # check if this is main repository directory
        if relativePath == '':
            return False, "Removing main repository directory is not allowed"
        # check if this is a repository directory
        if not self.is_repository_directory(relativePath):
            return False, "Given relative path '%s' is not a repository path"%relativePath
        # check if directory actually exists on disk
        realPath = os.path.join(self.__path,relativePath)
        if not os.path.isdir(realPath):
            return False, "Repository relative directory '%s' seems to be missing. call maintain_repository to fix all issues"
        # get and acquire lock
        L =  Locker(filePath=None, lockPass=str(uuid.uuid1()), lockPath=os.path.join(self.__path,parentPath,self.__dirLock))
        acquired, code = L.acquire_lock()
        if not acquired:
            error = "Code %s. Unable to aquire the lock when adding '%s'. All prior directories were added. You may try again, to finish adding directory"%(code,realPath)
            return False, error
        error = None
        try:
            dirList = self.__get_repository_parent_directory(relativePath=relativePath)
            assert dirList is not None, "Given relative path '%s' is not a repository directory"%(relativePath,)
            stateBefore = self.get_repository_state(relaPath=parentPath)
            _files = [f for f in dirList if isinstance(f, basestring)]
            _dirs  = [d for d in dirList if isinstance(d, dict)]
            _dirs  = [d for d in dirList if dirName not in d]
            _ = [dirList.pop(0) for _ in range(len(dirList))]
            dirList.extend(_files)
            dirList.extend(_dirs)
            if clean:
                shutil.rmtree(realPath)
            else:
                stateAfter = self.get_repository_state(relaPath=parentPath)
                success, errors = self.__clean_before_after(stateBefore=stateBefore, stateAfter=stateAfter, keepNoneEmptyDirectory=True)
                assert success, "\n".join(errors)
        except Exception as err:
            error = str(err)
        finally:
            L.release_lock()
        # return
        return error is None, error


    @path_required
    def rename_directory(self, relativePath, newName):
        """
        Rename a directory in the repository. It insures renaming the directory in the system.

        :Parameters:
            #. relativePath (string): The relative to the repository path of
               the directory to be renamed.
            #. newName (string): The new directory name.

        :Returns:
            #. success (boolean): Whether renaming the directory was successful.
            #. message (None, string): Some explanatory message or error reason
               why directory was not renamed.
        """
        relativePath = self.to_repo_relative_path(path=relativePath, split=False)
        parentPath, dirName = os.path.split(relativePath)
        if relativePath == '':
            return False, "Renaming main repository directory is not allowed"
        realPath = os.path.join(self.__path,relativePath)
        newRealPath = os.path.join(os.path.dirname(realPath), newName)
        if os.path.isdir(newRealPath):
            return False, "New directory path '%s' already exist"%(newRealPath,)
        # get directory parent list
        L =  Locker(filePath=None, lockPass=str(uuid.uuid1()), lockPath=os.path.join(self.__path,parentPath, self.__dirLock))
        acquired, code = L.acquire_lock()
        if not acquired:
            error = "Code %s. Unable to aquire the lock when adding '%s'. All prior directories were added. You may try again, to finish adding directory"%(code,dirPath)
            return False, error
        error = None
        try:
            dirList = self.__get_repository_parent_directory(relativePath=relativePath)
            assert dirList is not None, "Given relative path '%s' is not a repository directory"%(relativePath,)
            # change dirName in dirList
            _dirDict = [nd for nd in dirList  if isinstance(nd,dict)]
            _dirDict = [nd for nd in _dirDict if dirName in nd]
            assert len(_dirDict) == 1, "This should not have happened. Directory not found in repository. Please report issue"
            # rename directory
            os.rename(realPath, newRealPath)
            # update dirList
            _dirDict[0][newName] = _dirDict[0][dirName]
            _dirDict[0].pop(dirName)
            # update and dump dirinfo
            self.__save_dirinfo(info=None, dirInfoPath=parentPath, create=False)
        except Exception as err:
            error = str(err)
        finally:
            L.release_lock()
        if error is not None:
            _, error = self.save()
        # return
        return error is None, error


    @path_required
    def dump_file(self, value, relativePath,
                        description=None,
                        dump=None, pull=None,
                        replace=False):
        """
        Dump a file using its value to the system and creates its
        attribute in the Repository with utc timestamp.

        :Parameters:
            #. value (object): The value of a file to dump and add to the
               repository. It is any python object or file.
            #. relativePath (str): The relative to the repository path to where
               to dump the file.
            #. description (None, string): Any description about the file.
            #. dump (None, string): The dumping method.
               If None it will be set automatically to pickle and therefore the
               object must be pickleable. If a string is given, it can be a
               keyword ('json','pickle','dill') or a string compileable code to
               dump the data. The string code must include all the necessary
               imports and a '$FILE_PATH' that replaces the absolute file path
               when the dumping will be performed.\n
               e.g. "import numpy as np; np.savetxt(fname='$FILE_PATH', X=value, fmt='%.6e')"
            #. pull (None, string): The pulling method. If None it will be set
               automatically to pickle and therefore the object must be
               pickleable. If a string is given, it can be a keyword
               ('json','pickle','dill') or a string compileable code to pull
               the data. The string code must include all the necessary imports,
               a '$FILE_PATH' that replaces the absolute file path when the
               dumping will be performed and finally a PULLED_DATA variable.\n
               e.g "import numpy as np; PULLED_DATA=np.loadtxt(fname='$FILE_PATH')"
            #. replace (boolean): Whether to replace any existing file.

        :Returns:
            #. success (boolean): Whether renaming the directory was successful.
            #. message (None, string): Some explanatory message or error reason
               why directory was not dumped.
        """
        # check arguments
        assert isinstance(replace, bool), "replace must be boolean"
        if description is None:
            description = ''
        assert isinstance(description, basestring), "description must be None or a string"
        # convert dump and pull methods to strings
        if pull is None and dump is not None:
            if dump.startswith('pickle') or dump.startswith('dill') or dump.startswith('numpy') or dump =='json':
                pull = dump
        dump = get_dump_method(dump)
        pull = get_pull_method(pull)
        # check name and path
        relativePath = self.to_repo_relative_path(path=relativePath, split=False)
        savePath     = os.path.join(self.__path,relativePath)
        fPath, fName = os.path.split(savePath)
        # check if name is allowed
        success, reason = self.is_name_allowed(savePath)
        if not success:
            return False, reason
        # ensure directory added
        success, reason = self.add_directory(fPath)
        if not success:
            return False, reason
        # lock repository
        L =  Locker(filePath=None, lockPass=str(uuid.uuid1()), lockPath=os.path.join(fPath,self.__fileLock%fName))
        acquired, code = L.acquire_lock()
        if not acquired:
            error = "Code %s. Unable to aquire the lock when adding '%s'"%(code,relativePath)
            return False, error
        error = None
        # dump file
        try:
            isRepoFile,fileOnDisk, infoOnDisk, classOnDisk = self.is_repository_file(relativePath)
            if isRepoFile:
                assert replace, "file is a registered repository file. set replace to True to replace"
            fileInfoPath = os.path.join(self.__path,os.path.dirname(relativePath),self.__fileInfo%fName)
            if isRepoFile and fileOnDisk:
                with open(fileInfoPath, 'r') as fd:
                    info = json.load(fd)
                assert info['repository_unique_name'] == self.__repo['repository_unique_name'], "it seems that file was created by another repository"
                info['last_update_utctime'] = time.time()
            else:
                info = {'repository_unique_name':self.__repo['repository_unique_name']}
                info['create_utctime'] = info['last_update_utctime'] = time.time()
            info['dump'] = dump
            info['pull'] = pull
            info['description'] = description
            # get parent directory list if file is new and not being replaced
            if not isRepoFile:
                dirList = self.__get_repository_directory(fPath)
            # dump file
            exec( dump.replace("$FILE_PATH", str(savePath)) )
            # update info
            with open(fileInfoPath, 'w') as fd:
                json.dump( info,fd )
            # update class file
            fileClassPath = os.path.join(self.__path,os.path.dirname(relativePath),self.__fileClass%fName)
            with open(fileClassPath, 'wb') as fd:
                pickle.dump( value.__class__, fd, protocol=-1 )
            # add to repo if file is new and not being replaced
            if not isRepoFile:
                dirList.append(fName)
        except Exception as err:
            error = "unable to dump the file (%s)"%err
            if 'pickle.dump(' in dump:
                error += '\nmore info: %s'%str(get_pickling_errors(value))
        finally:
            L.release_lock()
        # save repository
        if error is not None:
            return False, error
        else:
            return self.save()


    def dump(self, *args, **kwargs):
        """Alias to dump_file"""
        self.dump_file(*args, **kwargs)


    @path_required
    def update_file(self, value, relativePath,
                          description=False,
                          dump=False, pull=False):
        """
        Update the value of a file that is already in the Repository.\n
        If file is not registered in repository, and error will be thrown.\n
        If file is missing in the system, it will be regenerated as dump method
        is called.

        :Parameters:
            #. value (object): The value of a file to update.
            #. relativePath (str): The relative to the repository path of the
               file to be updated.
            #. description (False, string): Any random description about the file.
               If False is given, the description info won't be updated,
               otherwise it will be update to what description argument value is.
            #. dump (False, string): The new dump method. If False is given,
               the old one will be used.
            #. pull (False, string): The new pull method. If False is given,
               the old one will be used.

       :Returns:
           #. success (boolean): Whether renaming the directory was successful.
           #. message (None, string): Some explanatory message or error reason
              why directory was not updated.
        """
        # check arguments
        assert description is False or description is None or isinstance(description, basestring), "description must be False, None or a string"
        assert dump is False or dump is None or isinstance(dump, basestring), "dump must be False, None or a string"
        assert pull is False or pull is None or isinstance(pull, basestring), "pull must be False, None or a string"
        # get name and path
        relativePath = self.to_repo_relative_path(path=relativePath, split=False)
        savePath     = os.path.join(self.__path,relativePath)
        fPath, fName = os.path.split(savePath)
        # get locker
        L =  Locker(filePath=None, lockPass=str(uuid.uuid1()), lockPath=os.path.join(fPath,self.__fileLock%fName))
        acquired, code = L.acquire_lock()
        if not acquired:
            error = "Code %s. Unable to aquire the lock when adding '%s'"%(code,relativePath)
            return False, error
        message = []
        updated = False
        try:
            # check file in repository
            isRepoFile,fileOnDisk, infoOnDisk, classOnDisk = self.is_repository_file(relativePath)
            assert isRepoFile, "file '%s' is not registered in repository, no update can be performed."%(relativePath,)
            # get file info
            if not fileOnDisk:
                assert description is not False,  "file '%s' is found on disk, description must be provided"%(relativePath,)
                assert dump is not False,  "file '%s' is found on disk, dump must be provided"%(relativePath,)
                assert pull is not False,  "file '%s' is found on disk, pull must be provided"%(relativePath,)
                info = {}
                info['repository_unique_name'] = self.__repo['repository_unique_name']
                info['create_utctime'] = info['last_update_utctime'] = time.time()
            else:
                with open(os.path.join(fPath,self.__fileInfo%fName), 'r') as fd:
                    info = json.load(fd)
                    info['last_update_utctime'] = time.time()
            if not fileOnDisk:
                message.append("file %s is registered in repository but it was found on disk prior to updating"%relativePath)
            if not infoOnDisk:
                message.append("%s is not found on disk prior to updating"%self.__fileInfo%fName)
            if not classOnDisk:
                message.append("%s is not found on disk prior to updating"%self.__fileClass%fName)
            # get dump and pull
            if (description is False) or (dump is False) or (pull is False):
                if description is False:
                    description = info['description']
                elif description is None:
                    description = ''
                if dump is False:
                    dump = info['dump']
                elif dump is None:
                    dump = get_dump_method(dump)
                if pull is False:
                    pull = info['pull']
                elif pull is None:
                    pull = get_pull_method(pull)
            # update dump, pull and description
            info['dump'] = dump
            info['pull'] = pull
            info['description'] = description
            # dump file
            exec( dump.replace("$FILE_PATH", str(savePath)) )
            # update info
            with open(os.path.join(fPath,self.__fileInfo%fName), 'w') as fd:
                json.dump( info,fd )
            # update class file
            fileClassPath = os.path.join(self.__path,os.path.dirname(relativePath),self.__fileClass%fName)
            with open(fileClassPath, 'wb') as fd:
                pickle.dump( value.__class__, fd, protocol=-1 )
        except Exception as err:
            message.append(str(err))
            updated = False
            if 'pickle.dump(' in dump:
                message.append('more info: %s'%str(get_pickling_errors(value)))
        else:
            updated = True
        finally:
            L.release_lock()
        # return
        return updated, '\n'.join(message)

    def update(self, *args, **kwargs):
        """Alias to update_file"""
        self.update_file(*args, **kwargs)


    @path_required
    def pull_file(self, relativePath, pull=None, update=True):
        """
        Pull a file's data from the Repository.

        :Parameters:
            #. relativePath (string): The relative to the repository path from
               where to pull the file.
            #. pull (None, string): The pulling method.
               If None, the pull method saved in the file info will be used.
               If a string is given, the string should include all the necessary
               imports, a '$FILE_PATH' that replaces the absolute file path when
               the dumping will be performed and finally a PULLED_DATA variable.
               e.g "import numpy as np; PULLED_DATA=np.loadtxt(fname='$FILE_PATH')"
            #. update (boolean): If pull is not None, Whether to update the pull
               method stored in the file info by the given pull method.

        :Returns:
            #. data (object): The pulled data from the file.
        """
        # check name and path
        relativePath = self.to_repo_relative_path(path=relativePath, split=False)
        realPath     = os.path.join(self.__path,relativePath)
        fPath, fName = os.path.split(realPath)
        # check whether it's a repository file
        isRepoFile,fileOnDisk, infoOnDisk, classOnDisk = self.is_repository_file(relativePath)
        if not isRepoFile:
            fileOnDisk  = ["",". File itself is found on disk"][fileOnDisk]
            infoOnDisk  = ["",". %s is found on disk"%self.__fileInfo%fName][infoOnDisk]
            classOnDisk = ["",". %s is found on disk"%self.__fileClass%fName][classOnDisk]
            assert False, "File '%s' is not a repository file.%s%s%s"%(relativePath,fileOnDisk,infoOnDisk,classOnDisk)
        assert fileOnDisk, "File '%s' is registered in repository but the file itself was not found on disk"%(relativePath,)
        if not infoOnDisk:
            if pull is not None:
                warnings.warn("'%s' was not found on disk but pull method is given"%(self.__fileInfo%fName))
            else:
                raise Exception("File '%s' is registered in repository but the '%s' was not found on disk and pull method is not specified"%(relativePath,(self.__fileInfo%fName)))
        # lock repository
        L =  Locker(filePath=None, lockPass=str(uuid.uuid1()), lockPath=os.path.join(fPath,self.__fileLock%fName))
        acquired, code = L.acquire_lock()
        if not acquired:
            error = "Code %s. Unable to aquire the lock when adding '%s'"%(code,relativePath)
            return False, error
        try:
            # get pull method
            if pull is not None:
                pull = get_pull_method(pull)
            else:
                with open(os.path.join(fPath,self.__fileInfo%fName), 'r') as fd:
                    info = json.load(fd)
                pull = info['pull']
            # try to pull file
            namespace = {}
            namespace.update( globals() )
            exec( pull.replace("$FILE_PATH", str(realPath) ), namespace )
        except Exception as err:
            L.release_lock()
            m = str(pull).replace("$FILE_PATH", str(realPath) )
            raise Exception("Unable to pull data using '%s' from file (%s)"%(m,err) )
        else:
            L.release_lock()
        # return data
        return namespace['PULLED_DATA']

    def pull(self, *args, **kwargs):
        """Alias to pull_file"""
        return self.pull_file(*args, **kwargs)


    @path_required
    def rename_file(self, relativePath, newRelativePath, force=False):
        """
        Rename a directory in the repository. It insures renaming the file in the system.

        :Parameters:
            #. relativePath (string): The relative to the repository path of
               the file that needst to be renamed.
            #. newRelativePath (string): The new relative to the repository path
               of where to move and rename the file.
            #. force (boolean): Whether to force renaming even when another
               repository file exists. In this case old repository file
               will be removed from the repository and the system as well.

        :Returns:
            #. success (boolean): Whether renaming the file was successful.
            #. message (None, string): Some explanatory message or error reason
               why directory was not updated.
        """
        assert isinstance(force, bool), "force must be boolean"
        # check old name and path
        relativePath = self.to_repo_relative_path(path=relativePath, split=False)
        realPath     = os.path.join(self.__path,relativePath)
        fPath, fName = os.path.split(realPath)
        # check new name and path
        newRelativePath = self.to_repo_relative_path(path=newRelativePath, split=False)
        newRealPath     = os.path.join(self.__path,newRelativePath)
        nfPath, nfName  = os.path.split(newRealPath)
        # lock old file
        LO =  Locker(filePath=None, lockPass=str(uuid.uuid1()), lockPath=os.path.join(fPath,self.__fileLock%fName))
        acquired, code = LO.acquire_lock()
        if not acquired:
            error = "Code %s. Unable to aquire the lock for old file '%s'"%(code,relativePath)
            return False, error
        # add new file diretory
        success, reason = self.add_directory(nfPath)
        if not success:
            return False, reason
        # create new file lock
        LN =  Locker(filePath=None, lockPass=str(uuid.uuid1()), lockPath=os.path.join(nfPath,self.__fileLock%nfName))
        acquired, code = LN.acquire_lock()
        if not acquired:
            error = "Code %s. Unable to aquire the lock for new file path '%s'"%(code,newRelativePath)
            return False, error
        renamed = False
        message = []
        try:
            # check whether it's a repository file
            isRepoFile,fileOnDisk, infoOnDisk, classOnDisk = self.is_repository_file(relativePath)
            assert isRepoFile,  "file '%s' is not a repository file"%(relativePath,)
            assert fileOnDisk,  "file '%s' is found on disk"%(relativePath,)
            assert infoOnDisk,  "%s is found on disk"%self.__fileInfo%fName
            assert classOnDisk, "%s is found on disk"%self.__fileClass%fName
            # get new file path
            nisRepoFile,nfileOnDisk,ninfoOnDisk,nclassOnDisk = self.is_repository_file(newRelativePath)
            assert not nisRepoFile or force, "New file path is a registered repository file, set force to True to proceed regardless"
            # get parent directories list
            oDirList = self.__get_repository_directory(fPath)
            nDirList = self.__get_repository_directory(nfPath)
            # remove new file and all repository files from disk
            if os.path.isfile(newRealPath):
                os.remove(newRealPath)
            if os.path.isfile(os.path.join(nfPath,self.__fileInfo%nfName)):
                os.remove(os.path.join(nfPath,self.__fileInfo%nfName))
            if os.path.isfile(os.path.join(nfPath,self.__fileClass%nfName)):
                os.remove(os.path.join(nfPath,self.__fileClass%nfName))
            # move old file to new path
            os.rename(realPath, newRealPath)
            os.rename(os.path.join(fPath,self.__fileInfo%fName), os.path.join(nfPath,self.__fileInfo%nfName))
            os.rename(os.path.join(fPath,self.__fileClass%fName), os.path.join(nfPath,self.__fileClass%nfName))
            # update list
            findex = oDirList.index(fName)
            oDirList.pop(findex)
            # update new list
            if nfName not in nDirList:
                nDirList.append(nfName)
        except Exception as err:
            renamed = False
            message.append(str(err))
        else:
            renamed = True
        finally:
            LO.release_lock()
            LN.release_lock()
        # always clean old file lock
        if os.path.isfile(os.path.join(fPath,self.__fileLock%fName)):
            os.remove(os.path.join(fPath,self.__fileLock%fName))
        # return
        return renamed, '\n'.join(message)


    @path_required
    def remove_file(self, relativePath, removeFromSystem=False):
        """
        Remove file from repository.

        :Parameters:
            #. relativePath (string): The relative to the repository path of the
               file to remove.
            #. removeFromSystem (boolean): Whether to remove file from disk as
               well.
        """
        assert isinstance(removeFromSystem, bool), "removeFromSystem must be boolean"
        # check name and path
        relativePath = self.to_repo_relative_path(path=relativePath, split=False)
        realPath     = os.path.join(self.__path,relativePath)
        fPath, fName = os.path.split(realPath)
        # lock repository
        L =  Locker(filePath=None, lockPass=str(uuid.uuid1()), lockPath=os.path.join(fPath,self.__fileLock%fName))
        acquired, code = L.acquire_lock()
        if not acquired:
            error = "Code %s. Unable to aquire the lock when adding '%s'"%(code,relativePath)
            return False, error
        removed = False
        message = []
        try:
            # check whether it's a repository file
            isRepoFile,fileOnDisk, infoOnDisk, classOnDisk = self.is_repository_file(relativePath)
            if not isRepoFile:
                message("File '%s' is not a repository file"%(relativePath,))
                if fileOnDisk:
                    message.append("File itself is found on disk")
                if infoOnDisk:
                    message.append("%s is found on disk"%self.__fileInfo%fName)
                if classOnDisk:
                    message.append("%s is found on disk"%self.__fileClass%fName)
            else:
                dirList = self.__get_repository_directory(fPath)
                findex  = dirList.index(fName)
                dirList.pop(findex)
                if os.path.isfile(realPath):
                    os.remove(realPath)
                if os.path.isfile(os.path.join(fPath,self.__fileInfo%fName)):
                    os.remove(os.path.join(fPath,self.__fileInfo%fName))
                if os.path.isfile(os.path.join(fPath,self.__fileClass%fName)):
                    os.remove(os.path.join(fPath,self.__fileClass%fName))
        except Exception as err:
            removed = False
            message.append(str(err))
        else:
            removed = True
        finally:
            L.release_lock()
        # always clean lock
        if os.path.isfile(os.path.join(fPath,self.__fileLock%fName)):
            os.remove(os.path.join(fPath,self.__fileLock%fName))
        # return
        return removed, '\n'.join(message)
