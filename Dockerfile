FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

COPY first_setup/ /tmp/first_setup/

RUN sed -i 's/\r//' /tmp/first_setup/setup.sh \
    && sed -i 's/sudo //g' /tmp/first_setup/setup.sh \
    && bash /tmp/first_setup/setup.sh \
    && ln -s /usr/bin/python3.12 /usr/bin/python3

WORKDIR /root/MoMProduction

ENTRYPOINT ["python3"]