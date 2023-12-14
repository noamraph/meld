# To build:
# docker build -t fourdiff .

# To run, add this to your .gitconfig:
#
# [mergetool "fourdiff"]
#     cmd = docker run --rm -it -v $(pwd):/workdir -v /tmp/.X11-unix:/tmp/.X11-unix -e DISPLAY=$DISPLAY -h $HOSTNAME -v $XAUTHORITY:/root/.Xauthority fourdiff /root/meld/bin/meld_git.py "$REMOTE" "$BASE" "$LOCAL" "$MERGED"
# [merge]
#     tool = fourdiff


FROM ubuntu:20.04

RUN apt-get update
RUN apt-get install -y --no-install-recommends meld libglib2.0-bin
COPY bin /root/meld/bin
COPY data /root/meld/data
COPY help /root/meld/help
COPY meld /root/meld/meld
COPY po /root/meld/po
COPY meld.doap /root/meld/
# We create a dummy .git, since this makes the script use "devel mode"
RUN mkdir /root/meld/.git
RUN mkdir /workdir
WORKDIR /workdir
CMD /root/meld/bin/meld_git.py
