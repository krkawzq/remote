FROM ubuntu:22.04

RUN apt update && \
    apt install -y openssh-server && \
    mkdir /run/sshd && \
    echo "root:123456" | chpasswd && \
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    sed -i 's/PasswordAuthentication no/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    echo "PermitRootLogin yes" >> /etc/ssh/sshd_config

CMD ["/usr/sbin/sshd", "-D"]

