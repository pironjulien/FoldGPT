/* SPDX-License-Identifier: GPL-3.0-only
 * Native lifecycle exerciser: every mode executes actual kernel operations.
 */
#define main managed_acquisition_fixture_main
#include "native-managed-fixture.c"
#undef main
static volatile sig_atomic_t interrupted;
static void interruption(int number){interrupted=number;}
int main(int argc,char **argv) {
    require(argc>=2,"native lifecycle args");
    require(getuid()!=0&&prctl(PR_GET_NO_NEW_PRIVS,0,0,0,0)==1&&prctl(PR_GET_SECCOMP,0,0,0,0)==2,"native lifecycle confinement");
    for(int fd=3;fd<128;fd++){errno=0;require(fcntl(fd,F_GETFD)<0&&errno==EBADF,"lifecycle descriptor boundary");}
    if(!strcmp(argv[1],"stdio")) {
        unsigned char out[]={0,255,128,'O','U','T'},err[]={254,0,'E','R','R'};
        require(write(1,out,sizeof(out))==sizeof(out),"binary stdout");
        require(write(2,err,sizeof(err))==sizeof(err),"binary stderr");return 17;
    }
    if(!strcmp(argv[1],"echo")) {
        require(argc==3,"echo byte count");size_t remaining=(size_t)strtoul(argv[2],NULL,10);
        unsigned char buffer[8192];
        while(remaining){size_t size=remaining<sizeof(buffer)?remaining:sizeof(buffer);ssize_t n=read(0,buffer,size);
            require(n>0,"real pipe stdin");require(write(1,buffer,(size_t)n)==n,"actual echo");remaining-=(size_t)n;}
        return 0;
    }
    if(!strcmp(argv[1],"eof")){char byte;require(read(0,&byte,1)==0,"actual closed pipe EOF");require(write(1,"EOF",3)==3,"EOF output");return 0;}
    if(!strcmp(argv[1],"interrupt")) {
        struct sigaction action={.sa_handler=interruption};sigemptyset(&action.sa_mask);
        require(sigaction(SIGINT,&action,NULL)==0,"actual interrupt handler");
        require(write(1,"READY",5)==5,"interrupt readiness");
        while(!interrupted)pause();
        require(interrupted==SIGINT,"real SIGINT");
        require(write(1,"INTERRUPTED",11)==11,"interrupt result");return 42;
    }
    if(!strcmp(argv[1],"env")) {
        require(dprintf(1,"ARG0=%s\n",argv[0])>0,"real argv0");
        for(char **p=environ;*p;p++)require(dprintf(1,"%s\n",*p)>0,"real explicit environment");
        return 0;
    }
    if(!strcmp(argv[1],"fork-exit")) {
        int syncpipe[2];require(pipe(syncpipe)==0,"descendant synchronization");
        pid_t child=fork();require(child>=0,"real descendant fork");
        if(!child){close(syncpipe[0]);dprintf(1,"CHILD:%d\n",getpid());require(write(syncpipe[1],"R",1)==1,"descendant readiness");for(;;)pause();}
        close(syncpipe[1]);char byte;require(read(syncpipe[0],&byte,1)==1,"wait descendant readiness");return 19;
    }
    if(!strcmp(argv[1],"output")) {
        unsigned char bytes[8192];memset(bytes,0xa5,sizeof(bytes));
        for(unsigned i=0;i<256;i++)require(write(1,bytes,sizeof(bytes))==sizeof(bytes),"actual large output");
        return 0;
    }
    return managed_acquisition_fixture_main(argc,argv);
}
