const express = require('express');
const path = require('path');
const app = express();
const port = 3000;

// Serve locally-installed vendor libraries (no CDN)
app.use('/vendor/dompurify', express.static(path.join(__dirname, 'node_modules', 'dompurify', 'dist')));

app.use(express.static('public'));

app.get('*', (req, res) => {
    res.sendFile(path.join(__dirname, 'public', 'index.html'));
});

app.listen(port, () => {
    console.log(`Mission Control UI running at http://localhost:${port}`);
});
