#define _GNU_SOURCE
#include <stdio.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <errno.h>
#include <unistd.h>
int main(int argc,char**argv){
 if(argc!=2)return 80;
 errno=0;int fd=open(argv[1],O_PATH|O_CLOEXEC);int err=errno;
 if(fd>=0){close(fd);return 81;}
 if(err!=EOPNOTSUPP){printf("unexpected open error=%d\n",err);return 82;}
 struct stat st;if(stat(argv[1],&st)||!S_ISDIR(st.st_mode))return 83;
 printf("actual O_PATH errno=%d; directory stat dev=%llu ino=%llu mode=%o\n",err,(unsigned long long)st.st_dev,(unsigned long long)st.st_ino,st.st_mode);
 return 0;
}
