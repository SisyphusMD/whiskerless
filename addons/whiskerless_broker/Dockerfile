FROM alpine:3.24

RUN apk add --no-cache mosquitto curl jq

COPY run.sh /run.sh
RUN chmod a+x /run.sh

CMD ["/run.sh"]
