function sendCommand(cmd) {
    fetch('/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ command: cmd })
    }).then(res => res.json())
      .then(data => console.log(data))
      .catch(err => console.error('Error sending command:', err));
}

function pollStatus() {
    fetch('/status')
        .then(res => res.json())
        .then(data => {
            const el = document.getElementById('status');
            if (data.state) {
                el.innerText = `Breaker Status: ${data.state}`;
            } else {
                el.innerText = `Error getting status`;
            }
        })
        .catch(err => {
            document.getElementById('status').innerText = 'Disconnected';
            console.error(err);
        });
}

setInterval(pollStatus, 2000);
