#define _GNU_SOURCE
#include <dlfcn.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
/* FFmpeg receives a pinned endpoint. All other outbound sockets fail closed. */
int connect(int fd,const struct sockaddr *a,socklen_t n){
 const char *ip=getenv("SK_STREAM_PIN_IP"),*port=getenv("SK_STREAM_PIN_PORT");char buf[INET6_ADDRSTRLEN]={0};int p=0;
 if(a->sa_family==AF_INET){const struct sockaddr_in *s=(const void*)a;inet_ntop(AF_INET,&s->sin_addr,buf,sizeof(buf));p=ntohs(s->sin_port);}
 else if(a->sa_family==AF_INET6){const struct sockaddr_in6 *s=(const void*)a;inet_ntop(AF_INET6,&s->sin6_addr,buf,sizeof(buf));p=ntohs(s->sin6_port);}
 else {errno=EACCES;return -1;}
 if(!ip||!port||strcmp(ip,buf)||p!=atoi(port)){errno=EACCES;return -1;}
 int(*real)(int,const struct sockaddr*,socklen_t)=dlsym(RTLD_NEXT,"connect");return real(fd,a,n);
}
ssize_t sendto(int fd,const void*b,size_t l,int f,const struct sockaddr*a,socklen_t n){if(a){errno=EACCES;return -1;}ssize_t(*real)(int,const void*,size_t,int,const struct sockaddr*,socklen_t)=dlsym(RTLD_NEXT,"sendto");return real(fd,b,l,f,a,n);}
ssize_t sendmsg(int fd,const struct msghdr*m,int f){if(m->msg_name){errno=EACCES;return -1;}ssize_t(*real)(int,const struct msghdr*,int)=dlsym(RTLD_NEXT,"sendmsg");return real(fd,m,f);}
