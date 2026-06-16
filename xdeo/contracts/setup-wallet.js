const { Wallet } = require('ethers');
const fs = require('fs');
const readline = require('readline');

const rl = readline.createInterface({
    input: process.stdin,
    output: process.stdout
});

console.log("\n=======================================================");
console.log("🔒 SECURE LOCAL WALLET SETUP (BASE MAINNET)");
console.log("=======================================================\n");
console.log("This script runs entirely on your local machine.");
console.log("Your keys will NOT be sent to the AI or the internet.");
console.log("It will generate your Private Key and save it directly to your .env file.\n");

rl.question('Paste your 12-word Coinbase Wallet Recovery Phrase here:\n> ', (phrase) => {
    try {
        const wallet = Wallet.fromPhrase(phrase.trim());
        const envContent = `DEPLOYER_PRIVATE_KEY=${wallet.privateKey}\n`;
        
        fs.writeFileSync('.env', envContent);
        
        console.log("\n✅ SUCCESS! Your Private Key has been successfully derived and saved to xdeo/contracts/.env");
        console.log("Wallet Address: " + wallet.address);
        console.log("\nYou can now safely close this prompt and tell me 'DONE' in the chat!");
    } catch (e) {
        console.log("\n❌ ERROR: Invalid recovery phrase. Make sure it is exactly 12 words separated by spaces.");
    }
    rl.close();
});
